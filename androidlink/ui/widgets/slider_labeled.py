from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget


def snap_value(value: int, minimum: int, maximum: int, step: int) -> int:
    """Rounds `value` to the nearest multiple of `step` within
    [minimum, maximum]. Used to give a slider a discrete "snap into place"
    feel (e.g. the Performance/Quality slider's resolution levels) instead
    of a fully continuous drag."""
    snapped = round(value / step) * step
    return max(minimum, min(maximum, snapped))


class LabeledSlider(QWidget):
    """A horizontal slider with a label at each end (e.g. Performance <-> Quality).

    With `snap_interval` set, the handle snaps to the nearest multiple of
    that interval as it's dragged (rather than stopping at an arbitrary
    pixel-derived value), with tick marks showing exactly where it'll land.
    """

    valueChanged = Signal(int)
    committed = Signal()  # fires once when the user releases the slider (for persistence)

    def __init__(
        self,
        left_label: str,
        right_label: str,
        minimum: int = 0,
        maximum: int = 100,
        value: int = 50,
        *,
        snap_interval: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._snap_interval = snap_interval

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        left = QLabel(left_label)
        left.setProperty("role", "mono")
        right = QLabel(right_label)
        right.setProperty("role", "mono")

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(minimum)
        self._slider.setMaximum(maximum)
        if snap_interval:
            self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            self._slider.setTickInterval(snap_interval)
            self._slider.setSingleStep(snap_interval)
            self._slider.setPageStep(snap_interval)
            value = snap_value(value, minimum, maximum, snap_interval)
        self._slider.setValue(value)
        self._slider.valueChanged.connect(self._on_value_changed)
        self._slider.sliderReleased.connect(self.committed)

        layout.addWidget(left)
        layout.addWidget(self._slider, stretch=1)
        layout.addWidget(right)

    def _on_value_changed(self, value: int) -> None:
        if self._snap_interval:
            snapped = snap_value(value, self._slider.minimum(), self._slider.maximum(), self._snap_interval)
            if snapped != value:
                self._slider.setValue(snapped)  # re-enters here with the snapped value; emits below then
                return
        self.valueChanged.emit(value)

    def value(self) -> int:
        return self._slider.value()

    def setValue(self, value: int) -> None:
        self._slider.setValue(value)

    def setToolTip(self, text: str) -> None:  # noqa: N802
        self._slider.setToolTip(text)
        super().setToolTip(text)
