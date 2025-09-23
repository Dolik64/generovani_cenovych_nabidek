#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jednoduchá scrollovací galerie obrázků (PNG) v PySide6 s klikacím výběrem.

Požadavky:
- Všechny obrázky jsou PNG a mají stejné rozlišení (např. 2839 × 1004).
- Obrázky se načítají ze zadané složky (změňte IMAGES_DIR níže).
- Kliknutím na obrázek se přepíná jeho označení: červený rámeček zap/vyp.
- Do terminálu se vypisuje, který obrázek byl vybrán / u kterého byl výběr zrušen.
- Galerie je scrollovací a obrázky se automaticky škálují na šířku viewportu.

Spuštění:
    pip install PySide6
    python pyside6_scroll_gallery.py

Poznámka: Pro jednoduchost je cesta k adresáři s obrázky nastavena konstantou
IMAGES_DIR níže. Upravte si ji na svou absolutní/relativní cestu.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# NASTAVTE SI CESTU NA SLOŽKU S PNG OBRÁZKY
IMAGES_DIR = Path("/Users/jirka/Downloads/tvorba cenovych nabidek/python/aplikace na generovani/pool/segmenty")
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<


class ClickableImage(QFrame):
    """Widget s obrázkem, který lze klikatelně označovat (toggle).

    - zobrazuje QPixmap škálovaný na cílovou šířku
    - při označení vykreslí červený rámeček (pomocí QSS)
    - emituje signál toggled(path, is_selected)
    """

    toggled = Signal(str, bool)

    def __init__(self, image_path: Path, target_width: int) -> None:
        super().__init__()
        self.setObjectName("imageFrame")  # pro QSS selektor
        self.setProperty("selected", False)
        self.setStyleSheet(
            # Rámeček je vždy 3 px, jen mění barvu -> neskáče layout
            """
            QFrame#imageFrame {
                border: 3px solid transparent;
                border-radius: 8px;
            }
            QFrame#imageFrame[selected="true"] {
                border-color: red;
            }
            """
        )

        self._image_path = Path(image_path)
        self._original = QPixmap(str(self._image_path))
        if self._original.isNull():
            raise ValueError(f"Nepodařilo se načíst obrázek: {self._image_path}")

        self._label = QLabel(alignment=Qt.AlignCenter)
        self._label.setObjectName("imageLabel")
        self._label.setMinimumSize(QSize(1, 1))
        self._label.setScaledContents(False)  # škálujeme ručně pro kvalitu

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(0)
        lay.addWidget(self._label)

        self.set_target_width(target_width)

    # ----------------------------- veřejné API ------------------------------ #
    @property
    def image_path(self) -> Path:
        return self._image_path

    @property
    def is_selected(self) -> bool:
        return bool(self.property("selected"))

    def set_selected(self, value: bool) -> None:
        self.setProperty("selected", bool(value))
        # Refresh stylu po změně dynamické property
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_target_width(self, width: int) -> None:
        """Nastaví novou cílovou šířku a přepočítá pixmapu se zachováním poměru."""
        width = max(1, int(width))
        scaled = self._original.scaledToWidth(width, Qt.SmoothTransformation)
        self._label.setPixmap(scaled)
        self._label.setFixedSize(scaled.size())

    # --------------------------- Qt event handlery -------------------------- #
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            new_state = not self.is_selected
            self.set_selected(new_state)
            if new_state:
                print(f"Vybráno: {self._image_path.name}")
            else:
                print(f"Zrušen výběr: {self._image_path.name}")
            self.toggled.emit(str(self._image_path), new_state)
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, images_dir: Path) -> None:
        super().__init__()
        self.setWindowTitle("PNG Galerie – klikací výběr (PySide6)")
        self.resize(1200, 900)

        self._items: list[ClickableImage] = []

        # ScrollArea
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        # Vnitřní obsah
        self._content = QWidget()
        self._vbox = QVBoxLayout(self._content)
        self._vbox.setContentsMargins(12, 12, 12, 12)
        self._vbox.setSpacing(12)

        self._scroll.setWidget(self._content)
        self.setCentralWidget(self._scroll)

        # Načti obrázky
        self.load_images(images_dir)

    # ------------------------------ logika --------------------------------- #
    def load_images(self, images_dir: Path) -> None:
        if not images_dir.exists() or not images_dir.is_dir():
            QMessageBox.critical(
                self,
                "Chyba",
                f"Adresář s obrázky neexistuje:\n{images_dir}",
            )
            return

        pngs = sorted([p for p in images_dir.iterdir() if p.suffix.lower() == ".png"])
        if not pngs:
            QMessageBox.information(self, "Info", f"V adresáři nejsou žádné PNG soubory:\n{images_dir}")
            return

        target_w = self._current_target_width()
        for path in pngs:
            try:
                item = ClickableImage(path, target_w)
            except Exception as e:  # chybné / poškozené soubory přeskoč
                print(f"Přeskakuji '{path.name}': {e}")
                continue

            # volitelné: připojit se na signál toggled, kdybyste chtěli reagovat i v UI
            item.toggled.connect(lambda p, s: None)

            self._items.append(item)
            self._vbox.addWidget(item, alignment=Qt.AlignHCenter)

        # pružný prostor na konci
        spacer = QWidget()
        spacer.setFixedHeight(1)
        self._vbox.addWidget(spacer)

    def _current_target_width(self) -> int:
        # necháme malou rezervu na vnitřní okraje
        viewport = self._scroll.viewport()
        if viewport is None:
            return 1000
        return max(300, viewport.width() - 36)

    def _update_all_widths(self) -> None:
        w = self._current_target_width()
        for item in self._items:
            item.set_target_width(w)

    # --------------------------- Qt event handlery -------------------------- #
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_all_widths()


def main() -> int:
    app = QApplication(sys.argv)

    try:
        window = MainWindow(IMAGES_DIR)
    except Exception as e:
        print(f"Chyba při vytváření okna: {e}")
        return 1

    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
