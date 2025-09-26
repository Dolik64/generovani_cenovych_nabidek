# -*- coding: utf-8 -*-
from pathlib import Path
from typing import List
from datetime import date

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QPixmap, QImage, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QListWidget, QListWidgetItem, QLabel, QPushButton, QDoubleSpinBox,
    QFileDialog, QMessageBox, QLineEdit, QTextEdit, QComboBox, QCheckBox, QGroupBox,
    QSplitter
)
from PIL.ImageQt import ImageQt

from config import (
    APP_TITLE, SEGMENT_POOL_DIR,
    MARGIN_CM_DEFAULT, GAP_CM_DEFAULT,
    A4_W_PT, A4_H_PT, PRICE_IMAGE_START_DIR, DEFAULT_EXPORT_DIR
)
from widgets.clickable_image import ClickableImage
from workers.preview_worker import PreviewWorker, PreviewEmitter
from pdf.export import export_pdf

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 860)

        self.price_image_path: str = ""
        self.preview_pages = []

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(140)
        self._preview_timer.timeout.connect(self.build_preview_async)

        # --- Horní panel (bez okrajů/mezery) ---
        top_bar = QWidget(); lay_top = QHBoxLayout(top_bar)
        btn_load = QPushButton("Načíst složku se segmenty (PNG)")
        btn_price = QPushButton("Načíst obrázek cenové tabulky")
        btn_pdf = QPushButton("Export PDF…")
        lay_top.addWidget(btn_load); lay_top.addWidget(btn_price); lay_top.addStretch(); lay_top.addWidget(btn_pdf)

        # --- Titulní strana ---
        cover_box = QGroupBox("Titulní strana"); lay_cover = QGridLayout(cover_box)
        self.edit_title = QLineEdit("CENOVÁ NABÍDKA SIMULÁTORU")
        self.edit_info = QTextEdit(); self.edit_info.setPlainText("Jiří Doležal\nNad Hrádkem 284\n25226 Kosoř")
        self.combo_date = QComboBox(); self.combo_date.addItems(["EN","CZ"]); self.combo_date.setCurrentText("EN")
        self.chk_today = QCheckBox("Použít dnešní datum"); self.chk_today.setChecked(True)
        lay_cover.addWidget(QLabel("Nadpis:"), 0, 0); lay_cover.addWidget(self.edit_title, 0, 1, 1, 3)
        lay_cover.addWidget(QLabel("Blok adresy (multi-řádek):"), 1, 0); lay_cover.addWidget(self.edit_info, 1, 1, 1, 3)
        lay_cover.addWidget(QLabel("Datum:"), 0, 4); lay_cover.addWidget(self.combo_date, 0, 5); lay_cover.addWidget(self.chk_today, 0, 6)

        # --- Galerie / Pořadí / Náhled (beze změn) ---
        self.gallery_scroll = QScrollArea(); self.gallery_scroll.setWidgetResizable(True)
        self.gallery_scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.gallery_content = QWidget()
        self.gallery_vbox = QVBoxLayout(self.gallery_content); self.gallery_vbox.setContentsMargins(12,12,12,12); self.gallery_vbox.setSpacing(12)
        self.gallery_scroll.setWidget(self.gallery_content)
        self._items: list[ClickableImage] = []
        self._item_by_path: dict[str, ClickableImage] = {}
        left_box = QWidget(); left_lay = QVBoxLayout(left_box); left_lay.addWidget(QLabel("Galerie segmentů")); left_lay.addWidget(self.gallery_scroll)

        mid_box = QWidget(); lay_mid = QVBoxLayout(mid_box)
        lay_mid.addWidget(QLabel("Vybrané (pořadí) – 4/stranu"))
        self.order_list = QListWidget(); lay_mid.addWidget(self.order_list)
        row_btns = QHBoxLayout(); btn_up = QPushButton("Nahoru"); btn_dn = QPushButton("Dolů"); btn_rm = QPushButton("Odebrat")
        row_btns.addWidget(btn_up); row_btns.addWidget(btn_dn); row_btns.addWidget(btn_rm); lay_mid.addLayout(row_btns)
        row_btns2 = QHBoxLayout(); btn_all = QPushButton("Vybrat vše"); btn_clr = QPushButton("Zrušit výběr")
        row_btns2.addWidget(btn_all); row_btns2.addWidget(btn_clr); lay_mid.addLayout(row_btns2)

        right_box = QWidget(); lay_right = QVBoxLayout(right_box)
        top_preview = QHBoxLayout(); top_preview.addWidget(QLabel("Stránka:"))
        self.page_combo = QComboBox(); self.page_combo.addItem("1")
        top_preview.addWidget(self.page_combo); top_preview.addStretch(); lay_right.addLayout(top_preview)
        self.preview_label = QLabel(alignment=Qt.AlignCenter); self.preview_label.setMinimumSize(400, 400)
        lay_right.addWidget(self.preview_label)

        splitter = QSplitter(); splitter.addWidget(left_box); splitter.addWidget(mid_box); splitter.addWidget(right_box); splitter.setSizes([450, 280, 600])

        central = QWidget(); v = QVBoxLayout(central); v.addWidget(top_bar); v.addWidget(cover_box); v.addWidget(splitter); self.setCentralWidget(central)

        self._make_menu()

        # Signály
        btn_load.clicked.connect(self.load_segments_dialog)
        btn_price.clicked.connect(self.load_price_image)
        btn_pdf.clicked.connect(self.export_pdf)

        btn_up.clicked.connect(self.move_up); btn_dn.clicked.connect(self.move_down); btn_rm.clicked.connect(self.remove_from_order)
        btn_all.clicked.connect(self.select_all); btn_clr.clicked.connect(self.clear_selection)

        self.page_combo.currentIndexChanged.connect(self.show_preview_page)
        self.edit_title.textChanged.connect(self.schedule_preview)
        self.edit_info.textChanged.connect(self.schedule_preview)
        self.combo_date.currentTextChanged.connect(self.schedule_preview)
        self.chk_today.toggled.connect(self.schedule_preview)

        # Most signálu z workeru
        self._emitter = PreviewEmitter()
        self._emitter.pages_ready.connect(self.accept_preview_pages)

        if SEGMENT_POOL_DIR.exists():
            self.load_segments_dir(SEGMENT_POOL_DIR)

    # ---- Menu ----
    def _make_menu(self):
        m = self.menuBar().addMenu("Soubor")
        act_open = QAction("Načíst složku…", self); act_open.triggered.connect(self.load_segments_dialog)
        act_price = QAction("Načíst ceníkový obrázek…", self); act_price.triggered.connect(self.load_price_image)
        act_pdf = QAction("Export PDF…", self); act_pdf.triggered.connect(self.export_pdf)
        m.addAction(act_open); m.addAction(act_price); m.addSeparator(); m.addAction(act_pdf)

    # ---- Galerie ----
    def load_segments_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Vyber složku se segmenty (PNG)")
        if d: self.load_segments_dir(Path(d))

    def load_segments_dir(self, directory: Path):
        for w in self._items: w.setParent(None)
        self._items.clear(); self._item_by_path.clear(); self.order_list.clear()

        if not directory.exists() or not directory.is_dir():
            QMessageBox.critical(self, "Chyba", f"Adresář neexistuje:\n{directory}"); return

        pngs = sorted(p for p in directory.iterdir() if p.suffix.lower() == ".png")
        if not pngs:
            QMessageBox.information(self, "Info", f"Žádné PNG v:\n{directory}"); return

        tgt = self._current_target_width()
        for p in pngs:
            try:
                item = ClickableImage(p, tgt)
            except Exception as e:
                print(f"Přeskakuji '{p.name}': {e}"); continue
            item.toggled.connect(self.on_image_toggled)
            self.gallery_vbox.addWidget(item, alignment=Qt.AlignHCenter)
            self._items.append(item); self._item_by_path[str(p)] = item

        spacer = QWidget(); spacer.setFixedHeight(1); self.gallery_vbox.addWidget(spacer)
        self.schedule_preview()

    def _current_target_width(self) -> int:
        vp = self.gallery_scroll.viewport()
        return max(300, (vp.width() - 36) if vp else 1000)

    def _update_all_widths(self) -> None:
        w = self._current_target_width()
        for item in self._items: item.set_target_width(w)

    # ---- Klikání / pořadí ----
    @Slot(str, bool)
    def on_image_toggled(self, path: str, is_selected: bool):
        if is_selected:
            if not self._order_contains(path):
                li = QListWidgetItem(Path(path).name); li.setData(Qt.UserRole, path)
                self.order_list.addItem(li)
        else:
            self._order_remove_by_path(path)
        self.schedule_preview()

    def _order_contains(self, path: str) -> bool:
        for i in range(self.order_list.count()):
            if self.order_list.item(i).data(Qt.UserRole) == path: return True
        return False

    def _order_remove_by_path(self, path: str):
        i = 0
        while i < self.order_list.count():
            if self.order_list.item(i).data(Qt.UserRole) == path:
                self.order_list.takeItem(i); return
            i += 1

    # ---- Výběrové operace ----
    def select_all(self):
        for it in self._items:
            if not it.is_selected:
                it.set_selected(True)
                p = str(it.image_path)
                if not self._order_contains(p):
                    li = QListWidgetItem(it.image_path.name); li.setData(Qt.UserRole, p)
                    self.order_list.addItem(li)
        self.schedule_preview()

    def clear_selection(self):
        for it in self._items:
            if it.is_selected: it.set_selected(False)
        self.order_list.clear()
        self.schedule_preview()

    def move_up(self):
        row = self.order_list.currentRow()
        if row <= 0: return
        it = self.order_list.takeItem(row)
        self.order_list.insertItem(row-1, it)
        self.order_list.setCurrentRow(row-1)
        self.schedule_preview()

    def move_down(self):
        row = self.order_list.currentRow()
        if row < 0 or row >= self.order_list.count()-1: return
        it = self.order_list.takeItem(row)
        self.order_list.insertItem(row+1, it)
        self.order_list.setCurrentRow(row+1)
        self.schedule_preview()

    def remove_from_order(self):
        row = self.order_list.currentRow()
        if row < 0: return
        p = self.order_list.item(row).data(Qt.UserRole)
        self.order_list.takeItem(row)
        w = self._item_by_path.get(p)
        if w and w.is_selected: w.set_selected(False)
        self.schedule_preview()

    # ---- Náhled (debounce + worker) ----
    def schedule_preview(self):
        self._preview_timer.start()

    def _order_paths(self) -> List[str]:
        return [self.order_list.item(i).data(Qt.UserRole) for i in range(self.order_list.count())]

    def build_preview_async(self):
        worker = PreviewWorker(
            order_paths=self._order_paths(),
            margin_cm=0.0,
            gap_cm=0.0,
            price_path=self.price_image_path,
            title=self.edit_title.text(),
            info_text=self.edit_info.toPlainText(),
            date_style=self.combo_date.currentText(),
            use_today=self.chk_today.isChecked(),
            emitter=self._emitter,
            width_px=900
        )
        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().start(worker)

    @Slot(object)
    def accept_preview_pages(self, pages):
        self.preview_pages = pages
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        self.page_combo.addItems([str(i+1) for i in range(len(pages))])
        self.page_combo.setCurrentIndex(0)
        self.page_combo.blockSignals(False)
        self.show_preview_page()

    def show_preview_page(self):
        if not self.preview_pages:
            self.preview_label.clear(); return
        idx = max(0, self.page_combo.currentIndex())
        from PIL import Image
        pil_img = self.preview_pages[idx]
        qimg = QImage(ImageQt(pil_img.convert("RGBA")))
        pm = QPixmap.fromImage(qimg)
        pm_scaled = pm.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(pm_scaled)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_all_widths()
        self.show_preview_page()

    # ---- Ceník ----
    def load_price_image(self):
        start_dir = str(PRICE_IMAGE_START_DIR) if PRICE_IMAGE_START_DIR and PRICE_IMAGE_START_DIR.exists() else ""
        p, _ = QFileDialog.getOpenFileName(
            self,
            "Vyber obrázek s cenovou tabulkou",
            start_dir,  # <- startovní adresář
            "Obrázky (*.png *.jpg *.jpeg *.webp *.tif *.tiff)"
        )
        if p:
            self.price_image_path = p
            self.schedule_preview()

    # ---- PDF ----
    def export_pdf(self):
        # navrhni název v DEFAULT_EXPORT_DIR
        try:
            DEFAULT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        suggested = DEFAULT_EXPORT_DIR / f"cenova_nabidka_{date.today().strftime('%Y-%m-%d')}.pdf"

        out, _ = QFileDialog.getSaveFileName(
            self, "Uložit PDF", str(suggested), "PDF (*.pdf)"
        )
        if not out:
            return
        try:
            export_pdf(
                out_path=out,
                order_paths=self._order_paths(),
                margin_cm=0.0,
                gap_cm=0.0,
                title_text=self.edit_title.text(),
                info_lines_text=self.edit_info.toPlainText(),
                date_style=self.combo_date.currentText(),
                use_today=self.chk_today.isChecked(),
                price_image_path=self.price_image_path or None,
            )
            print(f"[OK] PDF export dokončen: {out}")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se vytvořit PDF:\n{e}")