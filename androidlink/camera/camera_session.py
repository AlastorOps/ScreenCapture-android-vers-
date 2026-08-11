"""Drives a camera-mirroring scrcpy-server session (prompt.md section 11):
a separate session from screen casting (video_source=camera, no audio/
control at all) whose decoded frames feed a Windows virtual camera instead
of the on-screen render widget.

Mirrors streaming/transport.py's ScrcpyVideoClient video-socket state
machine (same config-packet/exception-safety/plausibility fixes — see that
module for why those matter) but simplified: exactly one socket, no audio,
no control. Kept as a separate class rather than unified with
ScrcpyVideoClient because the two have different threading needs: this one
also owns a QTimer that paces frames out to the virtual camera at a fixed
rate, decoupled from the bursty arrival of decoded frames — a webcam consumer
expects steady frame delivery, unlike the on-demand repaint of a Qt widget.
The timer and virtual camera I/O live on the worker thread (like
AudioPlayback in streaming/transport.py), never the GUI thread.

Same hardware-unverified caveat as streaming/transport.py: no Android
camera stream or virtual camera backend was available to test end-to-end
during development.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, QProcess, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer, QTcpSocket

from androidlink.camera.virtual_camera import VirtualCameraSink, VirtualCameraUnavailableError
from androidlink.streaming.decoder import UnsupportedCodecError, VideoDecoder
from androidlink.streaming.protocol import (
    DEVICE_NAME_FIELD_LENGTH,
    PACKET_HEADER_LENGTH,
    FrameMeta,
    SessionMeta,
    SCRCPY_SERVER_VERSION,
    build_camera_server_launch_args,
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
MAX_PLAUSIBLE_FRAME_DIMENSION = 16384


def _is_plausible_frame_size(width: int, height: int) -> bool:
    return 0 < width <= MAX_PLAUSIBLE_FRAME_DIMENSION and 0 < height <= MAX_PLAUSIBLE_FRAME_DIMENSION


class CameraClient(QObject):
    """Owns one camera-mirroring scrcpy-server session, its decoder, and the
    virtual camera output timer. Must live on a worker QThread (see
    CameraSession below) — never instantiate/use on the GUI thread."""

    session_started = Signal(int, int)
    connection_failed = Signal(str)
    virtual_camera_unavailable = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        adb_path: Path,
        serial: str,
        server_jar_path: Path,
        camera_id: str | None,
        camera_size: str | None,
        camera_facing: str | None,
        camera_fps: int,
    ) -> None:
        super().__init__()
        self._adb_path = adb_path
        self._serial = serial
        self._server_jar_path = server_jar_path
        self._camera_id = camera_id
        self._camera_size = camera_size
        self._camera_facing = camera_facing
        self._camera_fps = camera_fps

        self._scid = generate_scid()
        self._tcp_server: QTcpServer | None = None
        self._video_socket: QTcpSocket | None = None
        self._server_process: QProcess | None = None

        self._recv_buffer = bytearray()
        self._stage = "device_name"
        self._decoder: VideoDecoder | None = None
        self._codec_name: str | None = None
        self._pending_frame_meta: FrameMeta | None = None

        self._frame_box: LatestValueBox = LatestValueBox()
        self._sink: VirtualCameraSink | None = None
        self._output_timer: QTimer | None = None

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

        if self._output_timer is not None:
            self._output_timer.stop()
            self._output_timer = None

        if self._sink is not None:
            self._sink.close()
            self._sink = None

        if self._video_socket is not None:
            self._video_socket.close()
            self._video_socket = None

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
            *build_camera_server_launch_args(
                self._scid,
                camera_id=self._camera_id,
                camera_size=self._camera_size,
                camera_facing=self._camera_facing,
                camera_fps=self._camera_fps,
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
            logger.info("[scrcpy-server camera] %s", text)

    def _on_server_process_error(self, error: QProcess.ProcessError) -> None:
        if not self._stopping:
            logger.warning("scrcpy-server (camera) process error: %s", error)

    def _on_new_connection(self) -> None:
        if self._tcp_server is None or self._video_socket is not None:
            return
        self._video_socket = self._tcp_server.nextPendingConnection()
        # See streaming/transport.py's _disable_nagle() for why.
        self._video_socket.setSocketOption(QAbstractSocket.SocketOption.LowDelayOption, 1)
        self._video_socket.readyRead.connect(self._on_video_ready_read)
        self._video_socket.disconnected.connect(self._on_video_disconnected)

    def _on_video_disconnected(self) -> None:
        if not self._stopping:
            logger.warning("scrcpy-server camera socket disconnected unexpectedly")
            self.connection_failed.emit(errors.DEVICE_DISCONNECTED.text)

    def _on_video_ready_read(self) -> None:
        self._recv_buffer.extend(bytes(self._video_socket.readAll()))
        self._process_buffer()

    def _process_buffer(self) -> None:  # noqa: C901
        while True:
            if self._stage == "device_name":
                if len(self._recv_buffer) < DEVICE_NAME_FIELD_LENGTH:
                    return
                raw = bytes(self._recv_buffer[:DEVICE_NAME_FIELD_LENGTH])
                del self._recv_buffer[:DEVICE_NAME_FIELD_LENGTH]
                logger.info("Connected to scrcpy-server (camera) on %s", decode_device_name(raw))
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
                        logger.error(
                            "Implausible camera session size %dx%d; dropping connection",
                            meta.width,
                            meta.height,
                        )
                        self.connection_failed.emit(errors.CORRUPT_STREAM_DATA.text)
                        return
                    if self._decoder is not None:
                        self._decoder.close()
                    try:
                        self._decoder = VideoDecoder(self._codec_name)
                    except UnsupportedCodecError:
                        logger.error("Unsupported camera video codec: %s", self._codec_name)
                        self.connection_failed.emit(
                            errors.unsupported_video_codec(self._codec_name).text
                        )
                        return
                    self._start_virtual_camera(meta.width, meta.height)
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

                try:
                    if is_config:
                        self._decoder.set_extradata(raw)
                    else:
                        for frame in self._decoder.decode(raw):
                            self._frame_box.put(frame)
                except Exception:
                    logger.exception("Camera video decode error; dropping this packet")

                self._pending_frame_meta = None
                self._stage = "header"

    def _start_virtual_camera(self, width: int, height: int) -> None:
        if self._output_timer is not None:
            self._output_timer.stop()
            self._output_timer = None
        if self._sink is not None:
            self._sink.close()
            self._sink = None

        try:
            self._sink = VirtualCameraSink(width, height, self._camera_fps)
        except VirtualCameraUnavailableError as exc:
            logger.warning("Virtual camera unavailable: %s", exc)
            self.virtual_camera_unavailable.emit(errors.virtual_camera_unavailable(str(exc)).text)
            return

        logger.info(
            "Virtual camera active: %dx%d @ %dfps via %s",
            width,
            height,
            self._camera_fps,
            self._sink.backend_device_name,
        )
        self.session_started.emit(width, height)

        self._output_timer = QTimer(self)
        self._output_timer.setInterval(max(1, round(1000 / self._camera_fps)))
        self._output_timer.timeout.connect(self._push_latest_frame)
        self._output_timer.start()

    def _push_latest_frame(self) -> None:
        if self._sink is None:
            return
        frame = self._frame_box.take()
        if frame is not None:
            self._sink.send(frame)


class CameraSession(QObject):
    """GUI-thread-facing handle: owns the worker thread and re-exposes the
    client's signals, so callers never touch CameraClient directly."""

    session_started = Signal(int, int)
    connection_failed = Signal(str)
    virtual_camera_unavailable = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        adb_path: Path,
        serial: str,
        server_jar_path: Path,
        camera_id: str | None,
        camera_size: str | None,
        camera_facing: str | None,
        camera_fps: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._client = CameraClient(
            adb_path, serial, server_jar_path, camera_id, camera_size, camera_facing, camera_fps
        )
        self._client.moveToThread(self._thread)

        self._thread.started.connect(self._client.start)
        self._client.session_started.connect(self.session_started)
        self._client.connection_failed.connect(self.connection_failed)
        self._client.virtual_camera_unavailable.connect(self.virtual_camera_unavailable)
        self._client.stopped.connect(self._on_client_stopped)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        QMetaObject.invokeMethod(self._client, "stop", Qt.ConnectionType.QueuedConnection)

    def _on_client_stopped(self) -> None:
        self.stopped.emit()
        self._thread.quit()
        self._thread.wait(2000)
