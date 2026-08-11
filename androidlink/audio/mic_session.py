"""Drives a microphone-mirroring scrcpy-server session (prompt.md section
12): a separate session from screen casting/camera -- video disabled
entirely, audio_source set to one of MIC_AUDIO_SOURCES, no control -- whose
decoded PCM feeds a Windows virtual audio cable instead of the default
output device.

Because video is disabled, the audio socket becomes scrcpy-server's *first*
socket (see DesktopConnection.java's getFirstSocket(), and
protocol.build_mic_server_launch_args()'s docstring), so unlike the shared
Cast+Audio session in streaming/transport.py, this client must read the
64-byte device-name field itself before the 4-byte audio codec header.
Everything else about the audio state machine (codec header parsing,
disable-sentinel handling, config-packet/exception-safety pattern) mirrors
streaming/transport.py's audio stage directly.

Same hardware-unverified caveat as camera/camera_session.py: no Android
microphone stream or virtual-cable driver was available to test end-to-end
during development.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, QProcess, Qt, QThread, Signal, Slot
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer, QTcpSocket

from androidlink.audio.decoder import AudioDecoder, UnsupportedAudioCodecError
from androidlink.audio.virtual_audio import VirtualMicrophoneSink, VirtualMicrophoneUnavailableError
from androidlink.streaming.protocol import (
    DEVICE_NAME_FIELD_LENGTH,
    PACKET_HEADER_LENGTH,
    AudioStreamUnavailable,
    FrameMeta,
    SessionMeta,
    SCRCPY_SERVER_VERSION,
    AUDIO_SOURCE_MIC,
    build_mic_server_launch_args,
    decode_audio_header,
    decode_device_name,
    device_socket_name,
    generate_scid,
    parse_packet_header,
)
from androidlink.utils import errors

logger = logging.getLogger(__name__)

DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
ADB_COMMAND_TIMEOUT_MS = 10_000


class MicClient(QObject):
    """Owns one microphone-mirroring scrcpy-server session, its decoder, and
    the virtual-cable sink. Must live on a worker QThread (see MicSession
    below) -- never instantiate/use on the GUI thread."""

    session_started = Signal()
    connection_failed = Signal(str)
    audio_unavailable = Signal(bool)  # is_error -- device-side capture failure
    virtual_mic_unavailable = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        adb_path: Path,
        serial: str,
        server_jar_path: Path,
        audio_source: str,
    ) -> None:
        super().__init__()
        self._adb_path = adb_path
        self._serial = serial
        self._server_jar_path = server_jar_path
        self._audio_source = audio_source

        self._scid = generate_scid()
        self._tcp_server: QTcpServer | None = None
        self._audio_socket: QTcpSocket | None = None
        self._server_process: QProcess | None = None

        self._recv_buffer = bytearray()
        self._stage = "device_name"
        self._decoder: AudioDecoder | None = None
        self._sink: VirtualMicrophoneSink | None = None
        self._pending_frame_meta: FrameMeta | None = None
        self._volume = 1.0
        self._muted = False

        self._reverse_active = False
        self._stopping = False

    @Slot()
    def start(self) -> None:
        ok, output = self._run_adb_blocking(
            ["-s", self._serial, "push", str(self._server_jar_path), DEVICE_SERVER_PATH]
        )
        if not ok:
            logger.error("adb push scrcpy-server failed: %s", output)
            self.connection_failed.emit(errors.SERVER_PUSH_FAILED.text)
            return

        local_port = self._open_listener_and_reverse_tunnel()
        if local_port is None:
            self.connection_failed.emit(errors.REVERSE_TUNNEL_FAILED.text)
            return

        self._tcp_server.newConnection.connect(self._on_new_connection)

        if not self._launch_server_process():
            self.connection_failed.emit(errors.SERVER_LAUNCH_FAILED.text)

    @Slot()
    def stop(self) -> None:
        self._stopping = True

        if self._sink is not None:
            self._sink.stop()
            self._sink = None

        if self._audio_socket is not None:
            self._audio_socket.close()
            self._audio_socket = None

        if self._tcp_server is not None:
            self._tcp_server.close()
            self._tcp_server = None

        if self._server_process is not None:
            self._server_process.terminate()
            if not self._server_process.waitForFinished(2000):
                self._server_process.kill()
            self._server_process = None

        if self._reverse_active:
            self._run_adb_blocking(
                [
                    "-s",
                    self._serial,
                    "reverse",
                    "--remove",
                    f"localabstract:{device_socket_name(self._scid)}",
                ]
            )
            self._reverse_active = False

        if self._decoder is not None:
            self._decoder.close()
            self._decoder = None

        self.stopped.emit()

    @Slot(float)
    def set_volume(self, volume: float) -> None:
        self._volume = volume
        if self._sink is not None:
            self._sink.set_volume(volume)

    @Slot(bool)
    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        if self._sink is not None:
            self._sink.set_muted(muted)

    def _run_adb_blocking(self, args: list[str]) -> tuple[bool, str]:
        process = QProcess()
        process.start(str(self._adb_path), args)
        finished = process.waitForFinished(ADB_COMMAND_TIMEOUT_MS)
        if not finished:
            process.kill()
            return False, "adb command timed out"
        output = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        return process.exitCode() == 0, output

    def _open_listener_and_reverse_tunnel(self) -> int | None:
        server = QTcpServer()
        if not server.listen(QHostAddress.SpecialAddress.LocalHost, 0):
            logger.error("Could not open local TCP listener: %s", server.errorString())
            return None

        local_port = server.serverPort()
        socket_name = device_socket_name(self._scid)

        ok, output = self._run_adb_blocking(
            ["-s", self._serial, "reverse", f"localabstract:{socket_name}", f"tcp:{local_port}"]
        )
        if not ok:
            logger.error("adb reverse failed: %s", output)
            server.close()
            return None

        self._tcp_server = server
        self._reverse_active = True
        return local_port

    def _launch_server_process(self) -> bool:
        args = [
            "-s",
            self._serial,
            "shell",
            f"CLASSPATH={DEVICE_SERVER_PATH}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            SCRCPY_SERVER_VERSION,
            *build_mic_server_launch_args(self._scid, audio_source=self._audio_source),
        ]

        process = QProcess()
        process.setProgram(str(self._adb_path))
        process.setArguments(args)
        process.readyReadStandardOutput.connect(
            lambda: self._log_server_output(process, is_stderr=False)
        )
        process.readyReadStandardError.connect(
            lambda: self._log_server_output(process, is_stderr=True)
        )
        process.errorOccurred.connect(self._on_server_process_error)
        process.start()

        if not process.waitForStarted(ADB_COMMAND_TIMEOUT_MS):
            return False

        self._server_process = process
        return True

    def _log_server_output(self, process: QProcess, is_stderr: bool) -> None:
        stream = process.readAllStandardError() if is_stderr else process.readAllStandardOutput()
        text = bytes(stream).decode("utf-8", errors="replace").rstrip()
        if text:
            logger.info("[scrcpy-server mic] %s", text)

    def _on_server_process_error(self, error: QProcess.ProcessError) -> None:
        if not self._stopping:
            logger.warning("scrcpy-server (mic) process error: %s", error)

    def _on_new_connection(self) -> None:
        if self._tcp_server is None or self._audio_socket is not None:
            return
        self._audio_socket = self._tcp_server.nextPendingConnection()
        # See streaming/transport.py's _disable_nagle() for why.
        self._audio_socket.setSocketOption(QAbstractSocket.SocketOption.LowDelayOption, 1)
        self._audio_socket.readyRead.connect(self._on_audio_ready_read)
        self._audio_socket.disconnected.connect(self._on_audio_disconnected)

    def _on_audio_disconnected(self) -> None:
        if not self._stopping:
            logger.warning("scrcpy-server mic socket disconnected unexpectedly")
            self.connection_failed.emit(errors.DEVICE_DISCONNECTED.text)

    def _on_audio_ready_read(self) -> None:
        self._recv_buffer.extend(bytes(self._audio_socket.readAll()))
        self._process_buffer()

    def _process_buffer(self) -> None:  # noqa: C901
        while True:
            if self._stage == "device_name":
                if len(self._recv_buffer) < DEVICE_NAME_FIELD_LENGTH:
                    return
                raw = bytes(self._recv_buffer[:DEVICE_NAME_FIELD_LENGTH])
                del self._recv_buffer[:DEVICE_NAME_FIELD_LENGTH]
                logger.info("Connected to scrcpy-server (mic) on %s", decode_device_name(raw))
                self._stage = "audio_header"

            elif self._stage == "audio_header":
                if len(self._recv_buffer) < 4:
                    return
                raw = bytes(self._recv_buffer[:4])
                del self._recv_buffer[:4]
                try:
                    result = decode_audio_header(raw)
                except ValueError:
                    logger.error("Unrecognized microphone codec header")
                    self.audio_unavailable.emit(True)
                    self._stage = "disabled"
                    return

                if isinstance(result, AudioStreamUnavailable):
                    logger.warning(
                        "Android microphone unavailable (error=%s)", result.is_error
                    )
                    self.audio_unavailable.emit(result.is_error)
                    self._stage = "disabled"
                    return

                try:
                    self._decoder = AudioDecoder(result)
                except UnsupportedAudioCodecError:
                    logger.error("Unsupported microphone audio codec: %s", result)
                    self.audio_unavailable.emit(True)
                    self._stage = "disabled"
                    return

                self._start_virtual_mic()
                self._stage = "packet_header"

            elif self._stage == "packet_header":
                if len(self._recv_buffer) < PACKET_HEADER_LENGTH:
                    return
                raw = bytes(self._recv_buffer[:PACKET_HEADER_LENGTH])
                del self._recv_buffer[:PACKET_HEADER_LENGTH]
                meta = parse_packet_header(raw)

                if isinstance(meta, SessionMeta):
                    continue  # never sent for audio; ignore defensively

                self._pending_frame_meta = meta
                self._stage = "payload"

            elif self._stage == "payload":
                size = self._pending_frame_meta.packet_size
                if len(self._recv_buffer) < size:
                    return
                raw = bytes(self._recv_buffer[:size])
                del self._recv_buffer[:size]
                is_config = self._pending_frame_meta.is_config

                try:
                    if is_config:
                        self._decoder.set_extradata(raw)
                    else:
                        pcm = self._decoder.decode(raw)
                        if pcm and self._sink is not None:
                            self._sink.write(pcm)
                except Exception:
                    logger.exception("Microphone audio decode error; dropping this packet")

                self._pending_frame_meta = None
                self._stage = "packet_header"

            elif self._stage == "disabled":
                self._recv_buffer.clear()  # drain and ignore; mic capture failed on-device
                return

    def _start_virtual_mic(self) -> None:
        try:
            self._sink = VirtualMicrophoneSink()
        except VirtualMicrophoneUnavailableError as exc:
            logger.warning("Virtual microphone unavailable: %s", exc)
            self.virtual_mic_unavailable.emit(errors.virtual_microphone_unavailable(str(exc)).text)
            return

        self._sink.start()
        self._sink.set_volume(self._volume)
        self._sink.set_muted(self._muted)
        logger.info("Virtual microphone active via %s", self._sink.backend_device_name)
        self.session_started.emit()


class MicSession(QObject):
    """GUI-thread-facing handle: owns the worker thread and re-exposes the
    client's signals, so callers never touch MicClient directly."""

    session_started = Signal()
    connection_failed = Signal(str)
    audio_unavailable = Signal(bool)
    virtual_mic_unavailable = Signal(str)
    stopped = Signal()

    _volume_requested = Signal(float)
    _muted_requested = Signal(bool)

    def __init__(
        self,
        adb_path: Path,
        serial: str,
        server_jar_path: Path,
        *,
        audio_source: str = AUDIO_SOURCE_MIC,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._client = MicClient(adb_path, serial, server_jar_path, audio_source)
        self._client.moveToThread(self._thread)

        self._thread.started.connect(self._client.start)
        self._client.session_started.connect(self.session_started)
        self._client.connection_failed.connect(self.connection_failed)
        self._client.audio_unavailable.connect(self.audio_unavailable)
        self._client.virtual_mic_unavailable.connect(self.virtual_mic_unavailable)
        self._client.stopped.connect(self._on_client_stopped)
        self._volume_requested.connect(self._client.set_volume)
        self._muted_requested.connect(self._client.set_muted)

    def start(self) -> None:
        self._thread.start()

    def set_volume(self, volume: float) -> None:
        self._volume_requested.emit(volume)

    def set_muted(self, muted: bool) -> None:
        self._muted_requested.emit(muted)

    def stop(self) -> None:
        QMetaObject.invokeMethod(self._client, "stop", Qt.ConnectionType.QueuedConnection)

    def _on_client_stopped(self) -> None:
        self.stopped.emit()
        self._thread.quit()
        self._thread.wait(2000)
