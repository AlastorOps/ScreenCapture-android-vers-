"""Process-level CPU/RAM sampling for the Diagnostics readouts (prompt.md
section 20). Runs continuously (not just while casting) since it reflects
the whole app's resource usage.

GPU usage is deliberately not included: there's no reliable cross-vendor
way to read GPU utilization on Windows without either vendor-specific APIs
(NVML, NVIDIA-only) or querying the Performance Data Helper's "GPU Engine"
counters, which is a substantial undertaking on its own -- left as an
honest gap rather than a fabricated number (prompt.md section 33/34).
"""

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

SAMPLE_INTERVAL_MS = 1000


class SystemStatsSampler(QObject):
    sample_ready = Signal(float, float)  # cpu_percent (normalized to 0-100), ram_mb

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process = psutil.Process()
        self._cpu_count = psutil.cpu_count() or 1
        self._process.cpu_percent(interval=None)  # prime it; first real call is always 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(SAMPLE_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        cpu_percent = self._process.cpu_percent(interval=None) / self._cpu_count
        ram_mb = self._process.memory_info().rss / (1024 * 1024)
        self.sample_ready.emit(cpu_percent, ram_mb)
