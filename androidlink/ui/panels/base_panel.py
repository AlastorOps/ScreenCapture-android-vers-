from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class BasePanel(QFrame):
    """Common panel chrome: a titled header over a content area.

    Subclasses should add their widgets to `self.content_layout`.
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BasePanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._title_label = QLabel(title.upper())
        self._title_label.setProperty("role", "panel-title")
        outer.addWidget(self._title_label)

        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(8)
        outer.addWidget(content, stretch=1)

    def set_title_visible(self, visible: bool) -> None:
        self._title_label.setVisible(visible)
