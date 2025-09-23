# -*- coding: utf-8 -*-
from pathlib import Path
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

class ClickableImage(QFrame):
    """
    Klikatelný widget s obrázkem:
      - červený rámeček při označení (QSS)
      - škálování na cílovou šířku
      - signál toggled(path, is_selected)
    """
    toggled = Signal(str, bool)

    def __init__(self, image_path: Path, target_width: int) -> None:
        super().__init__()
        self.setObjectName("imageFrame")
        self.setProperty("selected", False)
        self.setStyleSheet("""
            QFrame#imageFrame {
                border: 3px solid transparent;
                border-radius: 8px;
                background: white;
            }
            QFrame#imageFrame[selected="true"] {
                border-color: red;
            }
        """)

        self._image_path = Path(image_path)
        self._original = QPixmap(str(self._image_path))
        if self._original.isNull():
            raise ValueError(f"Nepodařilo se načíst obrázek: {self._image_path}")

        self._label = QLabel(alignment=Qt.AlignCenter)
        self._label.setObjectName("imageLabel")
        self._label.setMinimumSize(QSize(1, 1))
        self._label.setScaledContents(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(0)
        lay.addWidget(self._label)

        self.set_target_width(target_width)

    @property
    def image_path(self) -> Path:
        return self._image_path

    @property
    def is_selected(self) -> bool:
        return bool(self.property("selected"))

    def set_selected(self, value: bool) -> None:
        if bool(self.property("selected")) == bool(value):
            return
        self.setProperty("selected", bool(value))
        # Refresh dynamické property -> přemaluje border
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_target_width(self, width: int) -> None:
        width = max(1, int(width))
        scaled = self._original.scaledToWidth(width, Qt.SmoothTransformation)
        self._label.setPixmap(scaled)
        self._label.setFixedSize(scaled.size())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            new_state = not self.is_selected
            self.set_selected(new_state)
            self.toggled.emit(str(self._image_path), new_state)
        super().mousePressEvent(event)