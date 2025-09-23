import os
import sys
import math
import datetime
from dataclasses import dataclass
from typing import List

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtGui import QImage
from PIL import Image, ImageDraw, ImageFont
from PIL.ImageQt import ImageQt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor

# ---- Konfigurace ----
APP_TITLE = "Tvorba cenové nabídky (PySide6, opraveno)"
SEGMENT_POOL_DIR = r"/Users/jirka/Downloads/tvorba cenovych nabidek/python/aplikace na generovani/pool/segmenty"
SEGMENTS_PER_PAGE_FIXED = 4

MARGIN_CM = 2.0
GAP_CM = 0.5
PRICE_TOP_OFFSET_CM = 2
A4_W_PT, A4_H_PT = A4

# Titulní strana
COVER_TITLE_COLOR_HEX = "#2E6F82"
COVER_LINE_THICKNESS_PT = 1
COVER_SIDE_MARGIN_CM = 1.2
COVER_BAND_TOP_CM = 4.5
COVER_BAND_BOTTOM_CM = 5.7
COVER_TITLE_SIZE_PT = 40
COVER_INFO_BLOCK_LEFT_CM = 1.5
COVER_INFO_BLOCK_BOTTOM_CM = 2.0
COVER_INFO_SIZE_PT = 12

def czech_date(d=None):
    if d is None:
        d = datetime.date.today()
    return d.strftime("%-d. %-m. %Y") if sys.platform != "win32" else d.strftime("%#d. %#m. %Y")

def english_date_upper(d=None):
    if d is None:
        d = datetime.date.today()
    return d.strftime("%B %d, %Y").upper()

def try_register_font():
    ttf_path = os.path.join(os.path.dirname(__file__), "DejaVuSans.ttf")
    if os.path.exists(ttf_path):
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", ttf_path))
            return "DejaVuSans", ttf_path
        except Exception:
            pass
    return "Helvetica", None

FONT_NAME, PREVIEW_TTF = try_register_font()

@dataclass
class SegmentItem:
    path: str
    name: str

# ---- Worker pro thumbnail (vlákno: vytváří QImage, ne QPixmap!) ----
class ThumbWorker(QtCore.QRunnable):
    def __init__(self, path: str, row: int, target_w: int, receiver: QtCore.QObject, slot_name: str):
        super().__init__()
        self.path = path
        self.row = row
        self.target_w = target_w
        self.receiver = receiver
        self.slot_name = slot_name

    def run(self):
        try:
            im = Image.open(self.path).convert("RGB")
            im.thumbnail((self.target_w, self.target_w // 2), Image.BILINEAR)
        except Exception:
            im = Image.new("RGB", (self.target_w, self.target_w // 2), "lightgray")
        qimg = QImage(ImageQt(im))  # thread-safe datový typ
        # pošli do GUI vlákna jako QImage
        QtCore.QMetaObject.invokeMethod(
            self.receiver,
            self.slot_name,
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(int, self.row),
            QtCore.Q_ARG(QImage, qimg)
        )

# ---- Worker pro stavbu náhledových stránek (PIL) ----
class PreviewWorker(QtCore.QRunnable):
    def __init__(self, order_paths: List[str], margin_cm: float, gap_cm: float,
                 price_path: str, title: str, info: str, date_style: str, use_today: bool,
                 receiver: QtCore.QObject, slot_name: str, width_px: int = 900):
        super().__init__()
        self.order_paths = order_paths
        self.margin_cm = margin_cm
        self.gap_cm = gap_cm
        self.price_path = price_path
        self.title = title
        self.info = info
        self.date_style = date_style
        self.use_today = use_today
        self.receiver = receiver
        self.slot_name = slot_name
        self.width_px = width_px

    def run(self):
        pages = []
        pages.append(self.render_cover())
        # komponenty 4/strana
        spp = SEGMENTS_PER_PAGE_FIXED
        total = len(self.order_paths)
        total_pages = math.ceil(total / spp) if total > 0 else 0
        for p in range(total_pages):
            paths = self.order_paths[p*spp:(p+1)*spp]
            pages.append(self.render_components(paths))
        pages.append(self.render_price())

        # Předání do GUI vlákna (list PIL.Image)
        QtCore.QMetaObject.invokeMethod(
            self.receiver,
            self.slot_name,
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(object, pages)  # předáme jako Python objekt
        )

    def _blank_a4(self):
        ratio = A4_H_PT / A4_W_PT
        w = self.width_px
        h = int(w * ratio)
        return Image.new("RGB", (w, h), "white")

    def render_cover(self):
        img = self._blank_a4()
        draw = ImageDraw.Draw(img)
        W, H = img.size
        col = tuple(int(COVER_TITLE_COLOR_HEX[i:i+2], 16) for i in (1,3,5))
        left = int(COVER_SIDE_MARGIN_CM * (W / (A4_W_PT / cm)))
        right = W - left
        y_top = int(COVER_BAND_TOP_CM * (H / (A4_H_PT / cm)))
        y_bot = int(COVER_BAND_BOTTOM_CM * (H / (A4_H_PT / cm)))
        draw.line([(left, y_top), (right, y_top)], fill=col, width=max(1, COVER_LINE_THICKNESS_PT//2 or 1))
        draw.line([(left, y_bot), (right, y_bot)], fill=col, width=max(1, COVER_LINE_THICKNESS_PT//2 or 1))
        try:
            font = ImageFont.truetype(PREVIEW_TTF or "DejaVuSans.ttf", COVER_TITLE_SIZE_PT)
        except Exception:
            font = ImageFont.load_default()
        title = (self.title.strip() or "CENOVÁ NABÍDKA").upper()
        th = draw.textbbox((0,0), title, font=font)[3]
        y_text = (y_top + y_bot - th) // 2
        draw.text((left, y_text), title, fill=col, font=font)

        try:
            info_font = ImageFont.truetype(PREVIEW_TTF or "DejaVuSans.ttf", COVER_INFO_SIZE_PT)
        except Exception:
            info_font = ImageFont.load_default()
        info_left = int(COVER_INFO_BLOCK_LEFT_CM * (W / (A4_W_PT / cm)))
        info_bottom = int(COVER_INFO_BLOCK_BOTTOM_CM * (H / (A4_H_PT / cm)))
        if self.use_today:
            date_str = english_date_upper() if self.date_style == "EN" else czech_date()
            draw.text((info_left, H - info_bottom - COVER_INFO_SIZE_PT*2), date_str, fill=col, font=info_font)
            y_start = H - info_bottom - COVER_INFO_SIZE_PT
        else:
            y_start = H - info_bottom
        for i, line in enumerate((self.info or "").splitlines()):
            draw.text((info_left, y_start + i*(COVER_INFO_SIZE_PT+4)), line, fill=col, font=info_font)
        return img

    def render_components(self, paths: List[str]):
        img = self._blank_a4()
        draw = ImageDraw.Draw(img)
        W, H = img.size
        margin_px = int(self.margin_cm * (W / (A4_W_PT / cm)))
        gap_px = int(self.gap_cm * (W / (A4_W_PT / cm)))
        usable_w = W - 2*margin_px
        usable_h = H - 2*margin_px
        total_gap = gap_px * max(0, SEGMENTS_PER_PAGE_FIXED-1)
        max_item_h = max(10, (usable_h - total_gap) // SEGMENTS_PER_PAGE_FIXED)
        y = margin_px
        for p in paths:
            try:
                im = Image.open(p).convert("RGB")
            except Exception:
                im = Image.new("RGB", (2839, 1004), "lightgray")
            w0, h0 = im.size
            scale = min(usable_w / w0, max_item_h / h0)
            nw, nh = max(1, int(w0*scale)), max(1, int(h0*scale))
            im2 = im.resize((nw, nh), Image.BILINEAR)
            x = margin_px + (usable_w - nw)//2
            img.paste(im2, (x, y))
            y += nh + gap_px
        draw.rectangle([0,0,W-1,H-1], outline="#dddddd")
        return img

    def render_price(self):
        img = self._blank_a4()
        draw = ImageDraw.Draw(img)
        W, H = img.size
        top_offset_px = int(PRICE_TOP_OFFSET_CM * (H / (A4_H_PT / cm)))
        margin_px = int(self.margin_cm * (W / (A4_W_PT / cm)))
        max_w = W - 2*margin_px
        max_h = H - top_offset_px - margin_px
        if self.price_path and os.path.exists(self.price_path):
            try:
                im = Image.open(self.price_path).convert("RGB")
            except Exception:
                im = Image.new("RGB", (1200,800), "lightgray")
        else:
            im = Image.new("RGB", (1200,800), "white")
            pd = ImageDraw.Draw(im)
            try:
                font = ImageFont.truetype(PREVIEW_TTF or "DejaVuSans.ttf", 36)
            except Exception:
                font = ImageFont.load_default()
            txt = "Cenová tabulka (obrázek nenahrán)"
            tw, th = pd.textbbox((0,0), txt, font=font)[2:4]
            pd.text(((1200-tw)//2, (800-th)//2), txt, fill="black", font=font)
        w0, h0 = im.size
        scale = min(max_w / w0, max_h / h0, 1.0)
        nw, nh = int(w0*scale), int(h0*scale)
        im2 = im.resize((nw, nh), Image.BILINEAR)
        x = (W - nw)//2
        y = top_offset_px
        img.paste(im2, (x, y))
        draw.rectangle([0,0,W-1,H-1], outline="#dddddd")
        return img

# ---- Hlavní okno ----
class MainWindow(QtWidgets.QMainWindow):
    @QtCore.Slot(int, QImage)
    def set_thumb_at_row(self, row: int, qimg: QImage):
        it = self.gallery.item(row)
        if it:
            pix = QtGui.QPixmap.fromImage(qimg)  # vytváříme v GUI vlákně
            it.setIcon(QtGui.QIcon(pix))

    @QtCore.Slot(list)
    def accept_preview_pages(self, pages):
        self.preview_pages = pages
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        self.page_combo.addItems([str(i+1) for i in range(len(pages))])
        self.page_combo.setCurrentIndex(0)
        self.page_combo.blockSignals(False)
        self.show_preview_page()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 820)

        self.margin_cm = MARGIN_CM
        self.gap_cm = GAP_CM
        self.price_image_path = ""
        self.pool = QtCore.QThreadPool.globalInstance()

        # TIMER MUSÍ EXISTOVAT DŘÍV, NEŽ PRVNÍ schedule_preview():
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self.build_preview_async)

        # výběr seg. a pořadí
        self.gallery = QtWidgets.QListWidget()
        self.gallery.setViewMode(QtWidgets.QListView.IconMode)
        self.gallery.setResizeMode(QtWidgets.QListView.Adjust)
        self.gallery.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.gallery.setIconSize(QtCore.QSize(260, 130))
        self.gallery.setUniformItemSizes(True)
        self.gallery.setSpacing(12)

        self.order = QtWidgets.QListWidget()
        self.order.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        btn_up = QtWidgets.QPushButton("Nahoru")
        btn_dn = QtWidgets.QPushButton("Dolů")
        btn_rm = QtWidgets.QPushButton("Odebrat")
        btn_all = QtWidgets.QPushButton("Vybrat vše")
        btn_clr = QtWidgets.QPushButton("Zrušit výběr")

        btn_up.clicked.connect(self.move_up)
        btn_dn.clicked.connect(self.move_down)
        btn_rm.clicked.connect(self.remove_from_order)
        btn_all.clicked.connect(self.select_all)
        btn_clr.clicked.connect(self.clear_selection)

        # náhled
        self.page_combo = QtWidgets.QComboBox()
        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.preview_pages = []

        # horní panel
        top_bar = QtWidgets.QWidget()
        lay_top = QtWidgets.QHBoxLayout(top_bar)
        btn_load = QtWidgets.QPushButton("Načíst složku se segmenty (PNG)")
        btn_price = QtWidgets.QPushButton("Načíst obrázek cenové tabulky")
        btn_pdf = QtWidgets.QPushButton("Export PDF…")
        lay_top.addWidget(btn_load)
        lay_top.addWidget(btn_price)
        lay_top.addStretch()
        lay_top.addWidget(QtWidgets.QLabel("Okraj (cm):"))
        self.spin_margin = QtWidgets.QDoubleSpinBox()
        self.spin_margin.setRange(0, 5); self.spin_margin.setSingleStep(0.5); self.spin_margin.setValue(self.margin_cm)
        lay_top.addWidget(self.spin_margin)
        lay_top.addWidget(QtWidgets.QLabel("Mezera (cm):"))
        self.spin_gap = QtWidgets.QDoubleSpinBox()
        self.spin_gap.setRange(0, 3); self.spin_gap.setSingleStep(0.5); self.spin_gap.setValue(self.gap_cm)
        lay_top.addWidget(self.spin_gap)
        lay_top.addWidget(btn_pdf)

        # Titulní strana: skutečně multi-řádkové pole
        cover_box = QtWidgets.QGroupBox("Titulní strana")
        lay_cover = QtWidgets.QGridLayout(cover_box)
        self.edit_title = QtWidgets.QLineEdit("CENOVÁ NABÍDKA SIMULÁTORU")
        self.edit_info = QtWidgets.QTextEdit()
        self.edit_info.setPlainText("Jiří Doležal\nNad Hrádkem 284\n25226 Kosoř")
        self.combo_date = QtWidgets.QComboBox(); self.combo_date.addItems(["EN", "CZ"]); self.combo_date.setCurrentText("EN")
        self.chk_today = QtWidgets.QCheckBox("Použít dnešní datum"); self.chk_today.setChecked(True)
        lay_cover.addWidget(QtWidgets.QLabel("Nadpis:"), 0, 0)
        lay_cover.addWidget(self.edit_title, 0, 1, 1, 3)
        lay_cover.addWidget(QtWidgets.QLabel("Blok adresy (multi-řádek):"), 1, 0)
        lay_cover.addWidget(self.edit_info, 1, 1, 1, 3)
        lay_cover.addWidget(QtWidgets.QLabel("Datum:"), 0, 4)
        lay_cover.addWidget(self.combo_date, 0, 5)
        lay_cover.addWidget(self.chk_today, 0, 6)

        # layout tří panelů
        left_box = QtWidgets.QWidget(); lay_left = QtWidgets.QVBoxLayout(left_box); lay_left.addWidget(QtWidgets.QLabel("Galerie segmentů")); lay_left.addWidget(self.gallery)
        mid_box = QtWidgets.QWidget()
        lay_mid = QtWidgets.QVBoxLayout(mid_box)
        lay_mid.addWidget(QtWidgets.QLabel("Vybrané (pořadí) – 4/stranu"))
        lay_mid.addWidget(self.order)
        bl = QtWidgets.QHBoxLayout(); bl.addWidget(btn_up); bl.addWidget(btn_dn); bl.addWidget(btn_rm); lay_mid.addLayout(bl)
        bl2 = QtWidgets.QHBoxLayout(); bl2.addWidget(btn_all); bl2.addWidget(btn_clr); lay_mid.addLayout(bl2)
        right_box = QtWidgets.QWidget()
        lay_right = QtWidgets.QVBoxLayout(right_box)
        ptop = QtWidgets.QHBoxLayout(); ptop.addWidget(QtWidgets.QLabel("Stránka:")); ptop.addWidget(self.page_combo); ptop.addStretch()
        lay_right.addLayout(ptop)
        lay_right.addWidget(self.preview_label)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(left_box); splitter.addWidget(mid_box); splitter.addWidget(right_box)
        splitter.setSizes([400, 280, 600])

        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)
        v.addWidget(top_bar)
        v.addWidget(cover_box)
        v.addWidget(splitter)
        self.setCentralWidget(central)

        # Signály
        btn_load.clicked.connect(self.load_segments_dialog)
        btn_price.clicked.connect(self.load_price_image)
        btn_pdf.clicked.connect(self.export_pdf)

        self.gallery.itemSelectionChanged.connect(self.on_gallery_selection_changed)
        self.page_combo.currentIndexChanged.connect(self.show_preview_page)
        self.spin_margin.valueChanged.connect(self.schedule_preview)
        self.spin_gap.valueChanged.connect(self.schedule_preview)
        self.edit_title.textChanged.connect(self.schedule_preview)
        self.edit_info.textChanged.connect(self.schedule_preview)
        self.combo_date.currentTextChanged.connect(self.schedule_preview)
        self.chk_today.toggled.connect(self.schedule_preview)

        # Přednačtení segmentů (až teď – timer už existuje)
        if SEGMENT_POOL_DIR and os.path.isdir(SEGMENT_POOL_DIR):
            self.load_segments_dir(SEGMENT_POOL_DIR)

    # ---- Načítání segmentů / galerie ----
    def load_segments_dialog(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Vyber složku se segmenty (PNG)")
        if d:
            self.load_segments_dir(d)

    def load_segments_dir(self, d):
        self.gallery.clear()
        paths = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".png")]
        paths.sort()
        for row, p in enumerate(paths):
            item = QtWidgets.QListWidgetItem(os.path.basename(p))
            item.setData(QtCore.Qt.UserRole, p)
            item.setIcon(self.placeholder_icon())
            self.gallery.addItem(item)
            # async thumb: posíláme QImage, ne QPixmap
            w = ThumbWorker(p, row, 260, self, "set_thumb_at_row")
            self.pool.start(w)
        # reset pořadí
        self.order.clear()
        self.schedule_preview()

    def placeholder_icon(self):
        pm = QtGui.QPixmap(260, 130)
        pm.fill(QtGui.QColor("#f0f0f0"))
        p = QtGui.QPainter(pm); p.setPen(QtGui.QPen(QtGui.QColor("#cccccc"))); p.drawRect(0,0,259,129); p.end()
        return QtGui.QIcon(pm)

    # ---- Výběr a pořadí ----
    def on_gallery_selection_changed(self):
        selected_paths = {it.data(QtCore.Qt.UserRole) for it in self.gallery.selectedItems()}
        order_paths = [self.order.item(i).data(QtCore.Qt.UserRole) for i in range(self.order.count())]

        # přidej nově vybrané na konec
        for it in self.gallery.selectedItems():
            p = it.data(QtCore.Qt.UserRole)
            if p not in order_paths:
                oi = QtWidgets.QListWidgetItem(it.text())
                oi.setData(QtCore.Qt.UserRole, p)
                self.order.addItem(oi)

        # odstraň z pořadí to, co už není vybrané
        i = 0
        while i < self.order.count():
            p = self.order.item(i).data(QtCore.Qt.UserRole)
            if p not in selected_paths:
                self.order.takeItem(i)
            else:
                i += 1

        self.schedule_preview()

    def select_all(self):
        with QtCore.QSignalBlocker(self.gallery):
            for i in range(self.gallery.count()):
                self.gallery.item(i).setSelected(True)
        self.on_gallery_selection_changed()

    def clear_selection(self):
        with QtCore.QSignalBlocker(self.gallery):
            for i in range(self.gallery.count()):
                self.gallery.item(i).setSelected(False)
        self.on_gallery_selection_changed()

    def move_up(self):
        row = self.order.currentRow()
        if row <= 0: return
        it = self.order.takeItem(row)
        self.order.insertItem(row-1, it)
        self.order.setCurrentRow(row-1)
        self.schedule_preview()

    def move_down(self):
        row = self.order.currentRow()
        if row < 0 or row >= self.order.count()-1: return
        it = self.order.takeItem(row)
        self.order.insertItem(row+1, it)
        self.order.setCurrentRow(row+1)
        self.schedule_preview()

    def remove_from_order(self):
        row = self.order.currentRow()
        if row < 0: return
        p = self.order.item(row).data(QtCore.Qt.UserRole)
        self.order.takeItem(row)
        # odznač v galerii
        for i in range(self.gallery.count()):
            if self.gallery.item(i).data(QtCore.Qt.UserRole) == p:
                with QtCore.QSignalBlocker(self.gallery):
                    self.gallery.item(i).setSelected(False)
                break
        self.schedule_preview()

    # ---- Náhled (debounce + thread) ----
    def schedule_preview(self):
        self._preview_timer.start()

    def build_preview_async(self):
        order_paths = [self.order.item(i).data(QtCore.Qt.UserRole) for i in range(self.order.count())]
        worker = PreviewWorker(
            order_paths=order_paths,
            margin_cm=float(self.spin_margin.value()),
            gap_cm=float(self.spin_gap.value()),
            price_path=self.price_image_path,
            title=self.edit_title.text(),
            info=self.edit_info.toPlainText(),
            date_style=self.combo_date.currentText(),
            use_today=self.chk_today.isChecked(),
            receiver=self,
            slot_name="accept_preview_pages",
            width_px=900
        )
        self.pool.start(worker)

    def show_preview_page(self):
        if not self.preview_pages:
            self.preview_label.clear()
            return
        idx = max(0, self.page_combo.currentIndex())
        pil_img = self.preview_pages[idx]
        qimg = QImage(ImageQt(pil_img.convert("RGBA")))
        pm = QtGui.QPixmap.fromImage(qimg)
        target = self.preview_label.size()
        pm_scaled = pm.scaled(target, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self.preview_label.setPixmap(pm_scaled)

    def resizeEvent(self, e: QtGui.QResizeEvent):
        super().resizeEvent(e)
        self.show_preview_page()

    # ---- Ceníkový obrázek ----
    def load_price_image(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Vyber obrázek s cenovou tabulkou",
                                                     "", "Obrázky (*.png *.jpg *.jpeg *.webp *.tif *.tiff)")
        if p:
            self.price_image_path = p
            self.schedule_preview()

    # ---- Export PDF ----
    def export_pdf(self):
        out, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Uložit PDF", "", "PDF (*.pdf)")
        if not out:
            return
        try:
            self._make_pdf(out)
            QtWidgets.QMessageBox.information(self, "Hotovo", f"PDF bylo vytvořeno:\n{out}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Chyba", f"Nepodařilo se vytvořit PDF:\n{e}")

    def _make_pdf(self, out_path):
        c = pdfcanvas.Canvas(out_path, pagesize=A4)
        W, H = A4_W_PT, A4_H_PT
        margin = self.margin_cm * cm
        gap = self.gap_cm * cm

        col = HexColor(COVER_TITLE_COLOR_HEX)
        left = COVER_SIDE_MARGIN_CM * cm
        right = W - left
        y_top = H - (COVER_BAND_TOP_CM * cm)
        y_bot = H - (COVER_BAND_BOTTOM_CM * cm)
        c.setStrokeColor(col); c.setLineWidth(COVER_LINE_THICKNESS_PT)
        c.line(left, y_top, right, y_top); c.line(left, y_bot, right, y_bot)

        title = (self.edit_title.text().strip() or "CENOVÁ NABÍDKA").upper()
        c.setFillColor(col); t = c.beginText()
        t.setTextOrigin(left, (y_top + y_bot)/2 - (COVER_TITLE_SIZE_PT*0.35))
        t.setFont(FONT_NAME, COVER_TITLE_SIZE_PT)
        try: t.setCharSpace(1.2)
        except Exception: pass
        t.textLine(title); c.drawText(t)

        info_x = COVER_INFO_BLOCK_LEFT_CM * cm
        info_y_base = COVER_INFO_BLOCK_BOTTOM_CM * cm
        c.setFont(FONT_NAME, COVER_INFO_SIZE_PT)
        if self.chk_today.isChecked():
            date_str = english_date_upper() if self.combo_date.currentText()=="EN" else czech_date()
            c.drawString(info_x, info_y_base + 3*(COVER_INFO_SIZE_PT+2), date_str)
            start_y = info_y_base + 2*(COVER_INFO_SIZE_PT+2)
        else:
            start_y = info_y_base
        for i, line in enumerate(self.edit_info.toPlainText().splitlines()):
            c.drawString(info_x, start_y + i*(COVER_INFO_SIZE_PT+2), line)

        c.showPage()

        order_paths = [self.order.item(i).data(QtCore.Qt.UserRole) for i in range(self.order.count())]
        n = len(order_paths); spp = SEGMENTS_PER_PAGE_FIXED
        if n > 0:
            total_pages = math.ceil(n / spp)
            usable_w = W - 2*margin
            usable_h = H - 2*margin
            total_gap = gap * max(0, spp-1)
            max_item_h = max(10, (usable_h - total_gap) / spp)
            for p in range(total_pages):
                start = p * spp
                end = min(start + spp, n)
                y = H - margin
                for path in order_paths[start:end]:
                    im = Image.open(path).convert("RGB")
                    w0, h0 = im.size
                    scale = min(usable_w / w0, max_item_h / h0)
                    nw, nh = int(w0*scale), int(h0*scale)
                    x = (W - nw) / 2
                    y -= nh
                    img_reader = ImageReader(im.resize((nw, nh), Image.LANCZOS))
                    c.drawImage(img_reader, x, y, width=nw, height=nh, preserveAspectRatio=False, mask='auto')
                    y -= gap
                c.showPage()

        y_top = H - PRICE_TOP_OFFSET_CM * cm
        max_w = W - 2*margin
        max_h = (H - (PRICE_TOP_OFFSET_CM * cm)) - margin
        if self.price_image_path and os.path.exists(self.price_image_path):
            im = Image.open(self.price_image_path).convert("RGB")
        else:
            im = Image.new("RGB", (1200,800), "white")
            dr = ImageDraw.Draw(im)
            try: f = ImageFont.truetype(PREVIEW_TTF or "DejaVuSans.ttf", 36)
            except Exception: f = ImageFont.load_default()
            txt = "Cenová tabulka (obrázek nenahrán)"
            tw, th = dr.textbbox((0,0), txt, font=f)[2:4]
            dr.text(((1200-tw)//2, (800-th)//2), txt, fill="black", font=f)

        w0, h0 = im.size
        scale = min(max_w / w0, max_h / h0, 1.0)
        nw, nh = int(w0*scale), int(h0*scale)
        x = (W - nw) / 2
        y = y_top - nh
        img_reader_price = ImageReader(im.resize((nw, nh), Image.LANCZOS))
        c.drawImage(img_reader_price, x, y, width=nw, height=nh, preserveAspectRatio=False, mask='auto')
        c.showPage(); c.save()

# ---- start ----
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())