# -*- coding: utf-8 -*-
import math
import os
from typing import List

from PySide6.QtCore import QRunnable, QObject, Signal
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.units import cm

from config import (
    A4_W_PT, A4_H_PT, SEGMENTS_PER_PAGE_FIXED, PRICE_TOP_OFFSET_CM,
    COVER_TITLE_COLOR_HEX, COVER_LINE_THICKNESS_PT, COVER_SIDE_MARGIN_CM,
    COVER_BAND_TOP_CM, COVER_BAND_BOTTOM_CM, COVER_TITLE_SIZE_PT,
    COVER_INFO_BLOCK_LEFT_CM, COVER_INFO_BLOCK_BOTTOM_CM, COVER_INFO_SIZE_PT,
    PREVIEW_TTF,PRICE_IMAGE_WIDTH_CM, czech_date, english_date_upper
)

class PreviewEmitter(QObject):
    pages_ready = Signal(list)  # list PIL.Image

class PreviewWorker(QRunnable):
    """
    Staví PIL náhledové stránky na pozadí a po dokončení emituje pages_ready(list).
    Komponentové stránky: 4 dlaždice na výšku, bez okrajů a mezer (edge-to-edge, cover).
    """
    def __init__(self, order_paths: List[str], margin_cm: float, gap_cm: float,
                 price_path: str, title: str, info_text: str,
                 date_style: str, use_today: bool,
                 emitter: PreviewEmitter, width_px: int = 900):
        super().__init__()
        self.order_paths = order_paths
        self.price_path = price_path
        self.title = title
        self.info_text = info_text
        self.date_style = date_style
        self.use_today = use_today
        self.emitter = emitter
        self.width_px = width_px

    def run(self):
        pages = []
        pages.append(self._render_cover_preview_pil())
        n = len(self.order_paths)
        spp = SEGMENTS_PER_PAGE_FIXED
        total_comp_pages = math.ceil(n / spp) if n > 0 else 0
        for p in range(total_comp_pages):
            paths = self.order_paths[p*spp:(p+1)*spp]
            pages.append(self._render_components_preview_pil(paths))
        pages.append(self._render_price_preview_pil())
        self.emitter.pages_ready.emit(pages)

    # ---- helpers ----
    def _blank_a4(self):
        ratio = A4_H_PT / A4_W_PT
        w = self.width_px
        h = int(w * ratio)
        return Image.new("RGB", (w, h), "white")

    def _render_cover_preview_pil(self):
        img = self._blank_a4()
        draw = ImageDraw.Draw(img)
        W, H = img.size
        col = tuple(int(COVER_TITLE_COLOR_HEX[i:i+2], 16) for i in (1,3,5))

        # Přepočty cm -> px (podle poměru A4 pt->px)
        px_per_pt_x = W / A4_W_PT
        px_per_pt_y = H / A4_H_PT
        pt_per_cm = 72.0 / 2.54
        px_per_cm_x = px_per_pt_x * pt_per_cm
        px_per_cm_y = px_per_pt_y * pt_per_cm

        left = int(COVER_SIDE_MARGIN_CM * px_per_cm_x)
        right = W - left
        y_top = int(COVER_BAND_TOP_CM * px_per_cm_y)       # horní linka pásu (menší y)
        y_bot = int(COVER_BAND_BOTTOM_CM * px_per_cm_y)    # dolní linka pásu (větší y)
        band_h = max(1, y_bot - y_top)

        # linky pásu
        draw.line([(left, y_top), (right, y_top)], fill=col, width=max(1, COVER_LINE_THICKNESS_PT//2 or 1))
        draw.line([(left, y_bot), (right, y_bot)], fill=col, width=max(1, COVER_LINE_THICKNESS_PT//2 or 1))

        # Helpery
        def font_px(size_pt):
            try:
                return ImageFont.truetype(PREVIEW_TTF or "DejaVuSans.ttf", size_pt)
            except Exception:
                return ImageFont.load_default()

        def text_w(s, f):
            bbox = draw.textbbox((0,0), s, font=f)
            return bbox[2] - bbox[0]

        def text_h(f):
            bbox = draw.textbbox((0,0), "Ag", font=f)
            return bbox[3] - bbox[1]

        # Nadpis: wrap + shrink + centrování
        title = (self.title.strip() or "CENOVÁ NABÍDKA").upper()
        fs = COVER_TITLE_SIZE_PT
        min_fs = 22
        leading_factor = 1.12

        def wrap_lines_px(text, fs_pt):
            f = font_px(fs_pt)
            lines, cur = [], ""
            max_w = right - left
            for w in text.split():
                test = (cur + " " + w).strip()
                if text_w(test, f) <= max_w:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
            return lines, f

        lines, f = wrap_lines_px(title, fs)
        while True:
            line_h = int(text_h(f) * leading_factor)
            if (len(lines) <= 2) and (max(text_w(L, f) for L in lines) <= (right - left)) and (len(lines)*line_h <= band_h):
                break
            if fs <= min_fs:
                break
            fs -= 1
            lines, f = wrap_lines_px(title, fs)

        line_h = int(text_h(f) * leading_factor)
        total_h = len(lines) * line_h
        y = y_top + (band_h - total_h) // 2  # VERTIKÁLNÍ CENTRUM

        for L in lines:
            x = left + (right - left - text_w(L, f)) // 2  # HORIZONTÁLNÍ CENTRUM
            draw.text((x, y), L, fill=col, font=f)
            y += line_h

        # Spodní blok: datum nad adresou
        info_left = int(COVER_INFO_BLOCK_LEFT_CM * px_per_cm_x)
        info_bottom = int(COVER_INFO_BLOCK_BOTTOM_CM * px_per_cm_y)
        f_info = font_px(COVER_INFO_SIZE_PT)
        line_h_info = int(text_h(f_info) * 1.15)
        gap_date = max(4, line_h_info // 3)

        info_lines = [ln for ln in (self.info_text or "").splitlines() if ln.strip()]
        total_info_h = len(info_lines) * line_h_info
        y_start = H - info_bottom - total_info_h
        y_run = y_start
        for ln in info_lines:
            draw.text((info_left, y_run), ln, fill=col, font=f_info)
            y_run += line_h_info

        if self.use_today:
            date_str = english_date_upper() if self.date_style == "EN" else czech_date()
            y_date = y_start - gap_date - (line_h_info - text_h(f_info))
            draw.text((info_left, max(0, y_date)), date_str, fill=col, font=f_info)

        return img

    def _render_components_preview_pil(self, paths):
        """
        4 dlaždice přes celou šířku, rovnoměrně na výšku, cover (ořez bez deformace),
        žádné okraje/mezeru.
        """
        img = self._blank_a4()
        W, H = img.size
        draw = ImageDraw.Draw(img)
        cell_h = H // SEGMENTS_PER_PAGE_FIXED
        y = 0

        target_ratio = W / cell_h  # poměr stran dlaždice

        for p in paths:
            try:
                im = Image.open(p).convert("RGB")
            except Exception:
                im = Image.new("RGB", (2839, 1004), "lightgray")

            iw, ih = im.size
            img_ratio = iw / ih

            # cover crop na poměr W:cell_h
            if img_ratio > target_ratio:
                # příliš široké -> ořež šířku
                new_w = int(ih * target_ratio)
                x0 = max(0, (iw - new_w) // 2)
                box = (x0, 0, x0 + new_w, ih)
            else:
                # příliš vysoké -> ořež výšku
                new_h = int(iw / target_ratio)
                y0 = max(0, (ih - new_h) // 2)
                box = (0, y0, iw, y0 + new_h)

            tile = im.crop(box).resize((W, cell_h), Image.LANCZOS)
            img.paste(tile, (0, y))
            y += cell_h

        # žádná bordura – celé edge-to-edge
        return img

    def _render_price_preview_pil(self):
        """
        Poslední stránka: horní odsazení v cm; šířka screenshotu pevně PRICE_IMAGE_WIDTH_CM,
        výška se dopočítá. Pokud by výška přesáhla dostupný prostor, zmenší se (šířka < 15 cm).
        """
        img = self._blank_a4()
        W, H = img.size

        # převod cm->px: vycházej z rozměru náhledu (W,H) vs. A4 v bodech
        px_per_pt_x = W / A4_W_PT
        px_per_pt_y = H / A4_H_PT
        pt_per_cm = 72.0 / 2.54
        px_per_cm_x = px_per_pt_x * pt_per_cm
        px_per_cm_y = px_per_pt_y * pt_per_cm

        top_offset_px = int(PRICE_TOP_OFFSET_CM * px_per_cm_y)
        target_w_px  = int(PRICE_IMAGE_WIDTH_CM * px_per_cm_x)
        max_h_px     = H - top_offset_px

        # načti/placeholder
        from PIL import Image, ImageDraw, ImageFont
        import os
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
            text = "Cenová tabulka (obrázek nenahrán)"
            tw, th = pd.textbbox((0,0), text, font=font)[2:4]
            pd.text(((1200-tw)//2, (800-th)//2), text, fill="black", font=font)

        w0, h0 = im.size

        # fit-to-width (15 cm), případně cap na výšku
        scale_w = target_w_px / w0
        target_h_px = int(h0 * scale_w)
        if target_h_px > max_h_px:
            scale = max_h_px / h0
        else:
            scale = scale_w

        nw, nh = max(1, int(w0*scale)), max(1, int(h0*scale))
        im2 = im.resize((nw, nh), Image.BILINEAR)
        x = (W - nw)//2
        y = top_offset_px
        img.paste(im2, (x, y))
        return img