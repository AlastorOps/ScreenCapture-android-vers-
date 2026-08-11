from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedLayout, QWidget

from androidlink.streaming.renderer import VideoRenderWidget
from androidlink.ui.panels.base_panel import BasePanel


class ScreenPanel(BasePanel):
    """Hosts the Android screen mirror.

    Shows a placeholder message until a cast session actually produces
    frames (Phase 3); the video widget only appears once real decoded
    frames arrive, never as a stand-in for a working pipeline.
    """

    render_fps_updated = Signal(float)
    fullscreen_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Screen", parent)

        toolbar_row = QWidget()
        toolbar_layout = QHBoxLayout(toolbar_row)
        toolbar_layout.setContentsMargins(0, 0, 0, 4)
        toolbar_layout.addStretch(1)
        self._fullscreen_button = QPushButton("⛶ Fullscreen")
        self._fullscreen_button.setCheckable(True)
        self._fullscreen_button.setToolTip("Toggle fullscreen (F11)")
        self._fullscreen_button.toggled.connect(self.fullscreen_toggled)
        toolbar_layout.addWidget(self._fullscreen_button)
        self.content_layout.addWidget(toolbar_row)

        stack_container = QWidget()
        self._stack = QStackedLayout(stack_container)

        self._placeholder_label = QLabel("Waiting for device")
        self._placeholder_label.setProperty("role", "placeholder")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.render_widget = VideoRenderWidget()
        self.render_widget.render_fps_updated.connect(self.render_fps_updated)

        self._stack.addWidget(self._placeholder_label)
        self._stack.addWidget(self.render_widget)
        self._stack.setCurrentWidget(self._placeholder_label)

        self.content_layout.addWidget(stack_container, stretch=1)

    def set_fullscreen_checked(self, checked: bool) -> None:
        """Reflects external fullscreen state changes (e.g. F11/Escape
        shortcuts) without re-emitting fullscreen_toggled."""
        self._fullscreen_button.blockSignals(True)
        self._fullscreen_button.setChecked(checked)
        self._fullscreen_button.blockSignals(False)

    def show_placeholder(self, text: str) -> None:
        self._placeholder_label.setText(text)
        self.render_widget.clear_frame()
        self._stack.setCurrentWidget(self._placeholder_label)

    def show_video(self) -> None:
        self._stack.setCurrentWidget(self.render_widget)
