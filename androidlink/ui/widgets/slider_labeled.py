from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget


class LabeledSlider(QWidget):
    """A horizontal slider with a label at each end (e.g. Performance <-> Quality)."""

    valueChanged = Signal(int)
    committed = Signal()  # fires once when the user releases the slider (for persistence)

    def __init__(
        self,
        left_label: str,
        right_label: str,
        minimum: int = 0,
        maximum: int = 100,
        value: int = 50,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

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
        self._slider.setValue(value)
        self._slider.valueChanged.connect(self.valueChanged)
        self._slider.sliderReleased.connect(self.committed)

        layout.addWidget(left)
        layout.addWidget(self._slider, stretch=1)
        layout.addWidget(right)

    def value(self) -> int:
        return self._slider.value()

    def setValue(self, value: int) -> None:
        self._slider.setValue(value)

    def setToolTip(self, text: str) -> None:  # noqa: N802
        self._slider.setToolTip(text)
        super().setToolTip(text)
