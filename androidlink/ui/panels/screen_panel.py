from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStackedLayout, QWidget

from androidlink.streaming.renderer import VideoRenderWidget
from androidlink.ui.panels.base_panel import BasePanel


class ScreenPanel(BasePanel):
    """Hosts the Android screen mirror.

    Shows a placeholder message until a cast session actually produces
    frames (Phase 3); the video widget only appears once real decoded
    frames arrive, never as a stand-in for a working pipeline.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Screen", parent)

        stack_container = QWidget()
        self._stack = QStackedLayout(stack_container)

        self._placeholder_label = QLabel("Waiting for device")
        self._placeholder_label.setProperty("role", "placeholder")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.render_widget = VideoRenderWidget()

        self._stack.addWidget(self._placeholder_label)
        self._stack.addWidget(self.render_widget)
        self._stack.setCurrentWidget(self._placeholder_label)

        self.content_layout.addWidget(stack_container, stretch=1)

    def show_placeholder(self, text: str) -> None:
        self._placeholder_label.setText(text)
        self.render_widget.clear_frame()
        self._stack.setCurrentWidget(self._placeholder_label)

    def show_video(self) -> None:
        self._stack.setCurrentWidget(self.render_widget)
