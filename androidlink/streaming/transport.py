"""Drives the vendored scrcpy-server over ADB and decodes its video socket.

Everything in this module runs on a worker QThread (see start_casting() at
the bottom) so ADB calls, socket I/O, and decoding never touch the UI thread
(prompt.md section 22). Only lightweight signals cross back to the GUI
thread.

NOTE: this has been verified against a real H.264 Annex-B stream at the
decoder level (tests/test_decoder.py) and the wire-protocol framing is
implemented directly from the scrcpy v4.1 source (see protocol.py), but the
end-to-end adb push / reverse tunnel / server launch / socket handshake
sequence has NOT been exercised against real hardware — there was no Android
device available during development. Treat this path as implemented-but-
hardware-unverified until tried against a real device.
"""

import logging
import time
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, QProcess, QTimer, Qt, QThread, Signal, Slot
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer, QTcpSocket

from androidlink.audio.decoder import AudioDecoder, UnsupportedAudioCodecError
from androidlink.audio.playback import AudioPlayback
from androidlink.streaming.decoder import UnsupportedCodecError, VideoDecoder
from androidlink.streaming.diagnostics import DiagnosticsSample
from androidlink.streaming.performance import StreamingProfile
from androidlink.streaming.protocol import (
    DEVICE_NAME_FIELD_LENGTH,
    PACKET_HEADER_LENGTH,
    AudioStreamUnavailable,
    FrameMeta,
    SessionMeta,
    SCRCPY_SERVER_VERSION,
    build_server_launch_args,
    decode_audio_header,
    decode_codec_id,
    decode_device_name,
    device_socket_name,
    generate_scid,
    parse_packet_header,
)
from androidlink.utils import errors
from androidlink.utils.latest_value_box import LatestValueBox

logger = logging.getLogger(__name__)

DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
ADB_COMMAND_TIMEOUT_MS = 10_000
MAX_PLAUSIBLE_FRAME_DIMENSION = 16384  # generous upper bound; catches corrupt/garbage parses
STATS_INTERVAL_MS = 1000


def _is_plausible_frame_size(width: int, height: int) -> bool:
    return 0 < width <= MAX_PLAUSIBLE_FRAME_DIMENSION and 0 < height <= MAX_PLAUSIBLE_FRAME_DIMENSION


def _disable_nagle(socket: QTcpSocket) -> None:
    """Nagle's algorithm (on by default) batches small writes for up to
    ~40-200ms waiting for either a full segment or a peer ACK before sending
    -- latency a real-time video/audio/control socket shouldn't be paying,
    and nothing in this codebase set TCP_NODELAY before now. Qt's
    LowDelayOption is a direct wrapper around setsockopt(TCP_NODELAY); the
    OS's TCP stack applies it the same way to a loopback socket (which is
    what `adb reverse` traffic over USB actually rides on, on the PC side)
    as to a real network one."""
    socket.setSocketOption(QAbstractSocket.SocketOption.LowDelayOption, 1)


class ScrcpyVideoClient(QObject):
    """Owns one scrcpy-server session's video socket. Must live on a worker
    QThread (see CastingSession below) — never instantiate/use on the GUI
    thread's event loop directly."""

    session_started = Signal(int, int)  # width, height
    frame_available = Signal()  # payload lives in the LatestValueBox
    connection_failed = Signal(str)
    audio_unavailable = Signal(bool)  # is_error
    audio_pcm_available = Signal(bytes)  # decoded PCM, e.g. for recording (48kHz stereo s16)
    stats_updated = Signal(object)  # DiagnosticsSample
    stopped = Signal()

    def __init__(
        self,
        adb_path: Path,
        serial: str,
        server_jar_path: Path,
        profile: StreamingProfile,
        frame_box: LatestValueBox,
        enable_control: bool = False,
        enable_audio: bool = False,
        audio_output_device_id: bytes | None = None,
        audio_secondary_output_device_id: bytes | None = None,
    ) -> None:
        super().__init__()
        self._adb_path = adb_path
        self._serial = serial
        self._server_jar_path = server_jar_path
        self._profile = profile
        self._frame_box = frame_box
        self._enable_control = enable_control
        self._enable_audio = enable_audio
        self._audio_output_device_id = audio_output_device_id
        self._audio_secondary_output_device_id = audio_secondary_output_device_id

        self._scid = generate_scid()
        self._tcp_server: QTcpServer | None = None
        self._video_socket: QTcpSocket | None = None
        self._audio_socket: QTcpSocket | None = None
        self._control_socket: QTcpSocket | None = None
        self._server_process: QProcess | None = None

        self._recv_buffer = bytearray()
        self._stage = "device_name"
        self._decoder: VideoDecoder | None = None
        self._codec_name: str | None = None
        self._pending_frame_meta: FrameMeta | None = None
        self._last_resolution: tuple[int, int] | None = None

        self._stats_timer: QTimer | None = None
        self._decoded_frame_count = 0
        self._bytes_received = 0
        self._decode_time_total = 0.0
        self._decode_count = 0

        self._audio_recv_buffer = bytearray()
        self._audio_stage = "audio_header"
        self._audio_decoder: AudioDecoder | None = None
        self._audio_playback: AudioPlayback | None = None
        self._pending_audio_frame_meta: FrameMeta | None = None
        self._audio_volume = 1.0
        self._audio_muted = False
        self._audio_pcm_logged = False
        self._audio_empty_decode_count = 0

        self._reverse_active = False
        self._stopping = False

    @Slot()
    def start(self) -> None:
        if not self._push_server():
            self.connection_failed.emit(errors.SERVER_PUSH_FAILED.text)
            return

        local_port = self._open_listener_and_reverse_tunnel()
        if local_port is None:
            self.connection_failed.emit(errors.REVERSE_TUNNEL_FAILED.text)
            return

        self._tcp_server.newConnection.connect(self._on_new_connection)

        if not self._launch_server_process():
            self.connection_failed.emit(errors.SERVER_LAUNCH_FAILED.text)
            return

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(STATS_INTERVAL_MS)
        self._stats_timer.timeout.connect(self._emit_stats)
        self._stats_timer.start()

    @Slot()
    def stop(self) -> None:
        self._stopping = True

        if self._stats_timer is not None:
            self._stats_timer.stop()
            self._stats_timer = None

        if self._video_socket is not None:
            self._video_socket.close()
            self._video_socket = None

        if self._audio_socket is not None:
            self._audio_socket.close()
            self._audio_socket = None

        if self._control_socket is not None:
            self._control_socket.close()
            self._control_socket = None

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

        if self._audio_playback is not None:
            self._audio_playback.stop()
            self._audio_playback = None

        if self._audio_decoder is not None:
            self._audio_decoder.close()
            self._audio_decoder = None

        self.stopped.emit()

    def take_latest_frame(self):
        return self._frame_box.take()

    def _run_adb_blocking(self, args: list[str]) -> tuple[bool, str]:
        process = QProcess()
        process.start(str(self._adb_path), args)
        finished = process.waitForFinished(ADB_COMMAND_TIMEOUT_MS)
        if not finished:
            process.kill()
            return False, "adb command timed out"
        output = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        return process.exitCode() == 0, output

    def _push_server(self) -> bool:
        ok, output = self._run_adb_blocking(
            ["-s", self._serial, "push", str(self._server_jar_path), DEVICE_SERVER_PATH]
        )
        if not ok:
            logger.error("adb push scrcpy-server failed: %s", output)
        return ok

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
            *build_server_launch_args(
                self._scid,
                video_bit_rate=self._profile.video_bit_rate,
                max_size=self._profile.max_size,
                max_fps=self._profile.max_fps,
                control=self._enable_control,
                audio=self._enable_audio,
            ),
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
            logger.info("[scrcpy-server] %s", text)

    def _on_server_process_error(self, error: QProcess.ProcessError) -> None:
        if not self._stopping:
            logger.warning("scrcpy-server process error: %s", error)

    def _on_new_connection(self) -> None:
        if self._tcp_server is None:
            return

        # scrcpy-server always connects in this order: video, then audio (if
        # enabled), then control (if enabled) — see DesktopConnection.open()
        # in the vendored jar.
        if self._video_socket is None:
            self._video_socket = self._tcp_server.nextPendingConnection()
            _disable_nagle(self._video_socket)
            self._video_socket.readyRead.connect(self._on_video_ready_read)
            self._video_socket.disconnected.connect(self._on_video_disconnected)
        elif self._enable_audio and self._audio_socket is None:
            self._audio_socket = self._tcp_server.nextPendingConnection()
            _disable_nagle(self._audio_socket)
            self._audio_socket.readyRead.connect(self._on_audio_ready_read)
            self._audio_socket.disconnected.connect(self._on_audio_disconnected)
        elif self._enable_control and self._control_socket is None:
            self._control_socket = self._tcp_server.nextPendingConnection()
            _disable_nagle(self._control_socket)

    def _on_video_disconnected(self) -> None:
        if not self._stopping:
            logger.warning("scrcpy-server video socket disconnected unexpectedly")
            self.connection_failed.emit(errors.DEVICE_DISCONNECTED.text)

    def _on_audio_disconnected(self) -> None:
        if not self._stopping:
            logger.warning("scrcpy-server audio socket disconnected unexpectedly")

    @Slot(bytes)
    def send_control_message(self, data: bytes) -> None:
        if self._control_socket is not None and self._control_socket.isOpen():
            self._control_socket.write(data)

    @Slot(float)
    def set_audio_volume(self, volume: float) -> None:
        self._audio_volume = volume
        if self._audio_playback is not None:
            self._audio_playback.set_volume(volume)

    @Slot(bool)
    def set_audio_muted(self, muted: bool) -> None:
        self._audio_muted = muted
        if self._audio_playback is not None:
            self._audio_playback.set_muted(muted)

    def _on_video_ready_read(self) -> None:
        data = bytes(self._video_socket.readAll())
        self._bytes_received += len(data)
        self._recv_buffer.extend(data)
        self._process_buffer()

    def _emit_stats(self) -> None:
        decode_latency_ms = (
            (self._decode_time_total / self._decode_count) * 1000 if self._decode_count else 0.0
        )
        sample = DiagnosticsSample(
            stream_fps=float(self._decoded_frame_count) * (1000 / STATS_INTERVAL_MS),
            dropped_frames=self._frame_box.take_dropped_count(),
            decode_latency_ms=decode_latency_ms,
            bitrate_bps=float(self._bytes_received) * 8 * (1000 / STATS_INTERVAL_MS),
            resolution=self._last_resolution,
            codec=self._codec_name,
            hardware_decode=self._decoder.hardware_accelerated if self._decoder is not None else None,
        )
        self.stats_updated.emit(sample)
        self._decoded_frame_count = 0
        self._bytes_received = 0
        self._decode_time_total = 0.0
        self._decode_count = 0

    def _process_buffer(self) -> None:  # noqa: C901 - simple linear state machine
        while True:
            if self._stage == "device_name":
                if len(self._recv_buffer) < DEVICE_NAME_FIELD_LENGTH:
                    return
                raw = bytes(self._recv_buffer[:DEVICE_NAME_FIELD_LENGTH])
                del self._recv_buffer[:DEVICE_NAME_FIELD_LENGTH]
                device_name = decode_device_name(raw)
                logger.info("Connected to scrcpy-server on %s", device_name)
                self._stage = "codec_id"

            elif self._stage == "codec_id":
                if len(self._recv_buffer) < 4:
                    return
                raw = bytes(self._recv_buffer[:4])
                del self._recv_buffer[:4]
                self._codec_name = decode_codec_id(raw)
                self._stage = "header"

            elif self._stage == "header":
                if len(self._recv_buffer) < PACKET_HEADER_LENGTH:
                    return
                raw = bytes(self._recv_buffer[:PACKET_HEADER_LENGTH])
                del self._recv_buffer[:PACKET_HEADER_LENGTH]
                meta = parse_packet_header(raw)

                if isinstance(meta, SessionMeta):
                    if not _is_plausible_frame_size(meta.width, meta.height):
                        # A corrupt/misaligned parse (e.g. after a prior
                        # decode error) can make random bytes look like a
                        # SessionMeta by chance; never act on nonsense sizes.
                        logger.error(
                            "Implausible video session size %dx%d; dropping connection",
                            meta.width,
                            meta.height,
                        )
                        self.connection_failed.emit(errors.CORRUPT_STREAM_DATA.text)
                        return
                    # A new encoder session always means fresh SPS/PPS.
                    if self._decoder is not None:
                        self._decoder.close()
                    try:
                        self._decoder = VideoDecoder(self._codec_name)
                    except UnsupportedCodecError:
                        logger.error("Unsupported video codec: %s", self._codec_name)
                        self.connection_failed.emit(
                            errors.unsupported_video_codec(self._codec_name).text
                        )
                        return
                    self._last_resolution = (meta.width, meta.height)
                    self.session_started.emit(meta.width, meta.height)
                else:
                    self._pending_frame_meta = meta
                    self._stage = "payload"

            elif self._stage == "payload":
                size = self._pending_frame_meta.packet_size
                if len(self._recv_buffer) < size:
                    return
                raw = bytes(self._recv_buffer[:size])
                del self._recv_buffer[:size]
                is_config = self._pending_frame_meta.is_config

                # However decode goes, this packet's bytes are already
                # consumed from the buffer above -- always advance the
                # parser state, or a single bad packet desyncs everything
                # after it (previously: an uncaught decode exception here
                # left the parser stuck mid-payload, so the NEXT packet's
                # header bytes got read as if they were more payload data,
                # cascading into garbage for the rest of the connection).
                try:
                    if is_config:
                        # Real Android encoders send SPS/PPS as a separate
                        # config buffer before the first keyframe, with no
                        # parameter sets repeated in-band in the keyframe
                        # itself -- the decoder needs them set explicitly.
                        self._decoder.set_extradata(raw)
                    else:
                        decode_start = time.perf_counter()
                        frames = self._decoder.decode(raw)
                        self._decode_time_total += time.perf_counter() - decode_start
                        self._decode_count += 1
                        for frame in frames:
                            self._decoded_frame_count += 1
                            self._frame_box.put(frame)
                            self.frame_available.emit()
                except Exception:
                    logger.exception("Video decode error; dropping this packet")

                self._pending_frame_meta = None
                self._stage = "header"

    def _on_audio_ready_read(self) -> None:
        self._audio_recv_buffer.extend(bytes(self._audio_socket.readAll()))
        self._process_audio_buffer()

    def _process_audio_buffer(self) -> None:
        while True:
            if self._audio_stage == "audio_header":
                if len(self._audio_recv_buffer) < 4:
                    return
                raw = bytes(self._audio_recv_buffer[:4])
                del self._audio_recv_buffer[:4]
                try:
                    result = decode_audio_header(raw)
                except ValueError:
                    # An unrecognized 4-byte codec id -- either a corrupt
                    # header or a codec this build's protocol.py doesn't
                    # know about. Audio degrades gracefully rather than
                    # tearing down the whole (video-carrying) session, the
                    # same way a device-reported AudioStreamUnavailable
                    # already does below.
                    logger.error("Unrecognized audio codec header; continuing without audio")
                    self.audio_unavailable.emit(True)
                    self._audio_stage = "disabled"
                    return

                if isinstance(result, AudioStreamUnavailable):
                    logger.warning(
                        "Android audio unavailable (error=%s); continuing without it",
                        result.is_error,
                    )
                    self.audio_unavailable.emit(result.is_error)
                    self._audio_stage = "disabled"
                    return

                try:
                    self._audio_decoder = AudioDecoder(result)
                    self._audio_playback = AudioPlayback(
                        self._audio_output_device_id, self._audio_secondary_output_device_id
                    )
                except UnsupportedAudioCodecError:
                    logger.error("Unsupported audio codec: %s", result)
                    self.audio_unavailable.emit(True)
                    self._audio_stage = "disabled"
                    return
                except RuntimeError:
                    logger.error("No audio output device available; continuing without audio")
                    self.audio_unavailable.emit(True)
                    self._audio_stage = "disabled"
                    return

                self._audio_playback.start()
                self._audio_playback.set_volume(self._audio_volume)
                self._audio_playback.set_muted(self._audio_muted)
                self._audio_pcm_logged = False
                self._audio_empty_decode_count = 0
                logger.info("Android audio session started (codec=%s)", result)
                self._audio_stage = "audio_packet_header"

            elif self._audio_stage == "audio_packet_header":
                if len(self._audio_recv_buffer) < PACKET_HEADER_LENGTH:
                    return
                raw = bytes(self._audio_recv_buffer[:PACKET_HEADER_LENGTH])
                del self._audio_recv_buffer[:PACKET_HEADER_LENGTH]
                meta = parse_packet_header(raw)

                if isinstance(meta, SessionMeta):
                    continue  # never sent for audio; ignore defensively

                self._pending_audio_frame_meta = meta
                self._audio_stage = "audio_payload"

            elif self._audio_stage == "audio_payload":
                size = self._pending_audio_frame_meta.packet_size
                if len(self._audio_recv_buffer) < size:
                    return
                raw = bytes(self._audio_recv_buffer[:size])
                del self._audio_recv_buffer[:size]
                is_config = self._pending_audio_frame_meta.is_config

                # Same reasoning as the video payload stage: always advance
                # past this packet regardless of decode success, or a single
                # bad packet desyncs the parser for everything after it.
                try:
                    if is_config:
                        self._audio_decoder.set_extradata(raw)
                    else:
                        pcm = self._audio_decoder.decode(raw)
                        if pcm:
                            self._audio_empty_decode_count = 0
                            self._audio_playback.write(pcm)
                            self.audio_pcm_available.emit(pcm)
                            if not self._audio_pcm_logged:
                                logger.info(
                                    "First Android audio PCM decoded and written (%d bytes)",
                                    len(pcm),
                                )
                                self._audio_pcm_logged = True
                        else:
                            # A decoder that never throws but also never
                            # yields a frame is a silent failure -- no
                            # exception, no audio_unavailable signal, just
                            # permanent silence. Surface it after enough
                            # consecutive empty decodes that it's clearly
                            # not just normal codec startup latency.
                            self._audio_empty_decode_count += 1
                            if self._audio_empty_decode_count == 50:
                                logger.warning(
                                    "Decoded 50 consecutive audio packets with no PCM output -- "
                                    "audio decode may be failing silently (bad/missing extradata?)"
                                )
                except Exception:
                    logger.exception("Audio decode error; dropping this packet")

                self._pending_audio_frame_meta = None
                self._audio_stage = "audio_packet_header"

            elif self._audio_stage == "disabled":
                self._audio_recv_buffer.clear()  # drain and ignore; audio is off
                return


class CastingSession(QObject):
    """GUI-thread-facing handle: owns the worker thread and re-exposes the
    client's signals, so callers never touch ScrcpyVideoClient directly."""

    session_started = Signal(int, int)
    frame_available = Signal()
    connection_failed = Signal(str)
    audio_unavailable = Signal(bool)
    audio_pcm_available = Signal(bytes)
    stats_updated = Signal(object)  # DiagnosticsSample
    stopped = Signal()

    # Connected (GUI thread) -> client slot (worker thread); Qt auto-promotes
    # these to queued connections since the receiver lives on a different
    # thread, safely marshaling the payload across.
    _control_message_requested = Signal(bytes)
    _audio_volume_requested = Signal(float)
    _audio_muted_requested = Signal(bool)

    def __init__(
        self,
        adb_path: Path,
        serial: str,
        server_jar_path: Path,
        profile: StreamingProfile,
        enable_control: bool = False,
        enable_audio: bool = False,
        audio_output_device_id: bytes | None = None,
        audio_secondary_output_device_id: bytes | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._frame_box: LatestValueBox = LatestValueBox()
        self._thread = QThread()
        self._client = ScrcpyVideoClient(
            adb_path,
            serial,
            server_jar_path,
            profile,
            self._frame_box,
            enable_control,
            enable_audio,
            audio_output_device_id,
            audio_secondary_output_device_id,
        )
        self._client.moveToThread(self._thread)

        self._thread.started.connect(self._client.start)
        self._client.session_started.connect(self.session_started)
        self._client.frame_available.connect(self.frame_available)
        self._client.connection_failed.connect(self.connection_failed)
        self._client.audio_unavailable.connect(self.audio_unavailable)
        self._client.audio_pcm_available.connect(self.audio_pcm_available)
        self._client.stats_updated.connect(self.stats_updated)
        self._client.stopped.connect(self._on_client_stopped)
        self._control_message_requested.connect(self._client.send_control_message)
        self._audio_volume_requested.connect(self._client.set_audio_volume)
        self._audio_muted_requested.connect(self._client.set_audio_muted)

    def start(self) -> None:
        self._thread.start()

    def send_control_message(self, data: bytes) -> None:
        self._control_message_requested.emit(data)

    def set_audio_volume(self, volume: float) -> None:
        self._audio_volume_requested.emit(volume)

    def set_audio_muted(self, muted: bool) -> None:
        self._audio_muted_requested.emit(muted)

    def stop(self) -> None:
        # ScrcpyVideoClient lives on the worker thread; invoke its stop()
        # slot there rather than touching its sockets/QProcess from the GUI
        # thread. QueuedConnection is safe here even if this somehow runs on
        # the worker thread itself (it just defers to the next event loop
        # iteration).
        QMetaObject.invokeMethod(self._client, "stop", Qt.ConnectionType.QueuedConnection)

    def take_latest_frame(self):
        return self._client.take_latest_frame()

    def _on_client_stopped(self) -> None:
        self.stopped.emit()
        self._thread.quit()
        self._thread.wait(2000)
