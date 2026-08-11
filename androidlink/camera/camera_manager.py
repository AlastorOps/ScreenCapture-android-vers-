"""Queries a connected device's cameras (prompt.md section 11: "Detect all
available cameras") by launching scrcpy-server in its `list_cameras=true`
mode, which just prints capability info to stdout and exits — no socket
connection, no ADB reverse tunnel needed.

Runs via async QProcess (not blocking waitForFinished()) so this never
stalls the GUI thread, even though it's a quick one-shot operation.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from androidlink.camera.camera_list import parse_camera_list
from androidlink.streaming.protocol import SCRCPY_SERVER_VERSION, build_list_cameras_args, generate_scid

logger = logging.getLogger(__name__)

DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
LIST_TIMEOUT_MS = 15_000


class CameraManager(QObject):
    cameras_listed = Signal(list)  # list[CameraInfo]
    list_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._output = bytearray()

    def is_busy(self) -> bool:
        return self._process is not None

    def list_cameras(self, adb_path: Path, serial: str, server_jar_path: Path) -> None:
        if self._process is not None:
            logger.warning("Camera list already in progress; ignoring new request")
            return

        push = QProcess(self)
        push.finished.connect(
            lambda code, _status: self._on_push_finished(code, adb_path, serial, server_jar_path)
        )
        push.start(str(adb_path), ["-s", serial, "push", str(server_jar_path), DEVICE_SERVER_PATH])
        self._process = push

    def _on_push_finished(self, exit_code: int, adb_path: Path, serial: str, _jar: Path) -> None:
        self._process = None
        if exit_code != 0:
            self.list_failed.emit("Could not push scrcpy-server to the device")
            return

        args = [
            "-s",
            serial,
            "shell",
            f"CLASSPATH={DEVICE_SERVER_PATH}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            SCRCPY_SERVER_VERSION,
            *build_list_cameras_args(generate_scid()),
        ]

        self._output = bytearray()
        process = QProcess(self)
        process.readyReadStandardOutput.connect(lambda: self._collect_output(process, False))
        process.readyReadStandardError.connect(lambda: self._collect_output(process, True))
        process.finished.connect(self._on_list_finished)
        process.errorOccurred.connect(self._on_list_error)
        process.setProgram(str(adb_path))
        process.setArguments(args)
        process.start()
        self._process = process

    def _collect_output(self, process: QProcess, is_stderr: bool) -> None:
        chunk = process.readAllStandardError() if is_stderr else process.readAllStandardOutput()
        self._output += bytes(chunk)

    def _on_list_finished(self, _exit_code: int, _status) -> None:
        self._process = None
        text = self._output.decode("utf-8", errors="replace")
        logger.info("Camera list output: %s", text.strip())
        cameras = parse_camera_list(text)
        self.cameras_listed.emit(cameras)

    def _on_list_error(self, error: QProcess.ProcessError) -> None:
        if self._process is not None:
            self._process = None
            logger.error("Camera list process error: %s", error)
            self.list_failed.emit("Could not query the device's cameras")
