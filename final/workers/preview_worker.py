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
    PREVIEW_TTF, PRICE_IMAGE_WIDTH_CM, COVER_TITLE_OFFSET_MM, czech_date, english_date_upper,
    COVER_TOP_LINE_COLOR_HEX, COVER_BOTTOM_LINE_COLOR_HEX,COMPONENT_MARGIN_MM,
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
        """
        Titulní strana – náhled v PIL sjednocený s PDF:
        - linky pásu (horní/dolní) v barvách z configu
        - nadpis centrovaný v pásu, kreslený po baseline (ascent/descent), s COVER_TITLE_OFFSET_MM
        - infoblok u spodního okraje, také po baseline
        - datum volitelně nad infoblokem
        """
        img = self._blank_a4()
        draw = ImageDraw.Draw(img)
        W, H = img.size

        # --- barvy a převody jednotek ---
        def hex_to_rgb(h): return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))
        col_title   = hex_to_rgb(COVER_TITLE_COLOR_HEX)
        col_line_top = hex_to_rgb(COVER_TOP_LINE_COLOR_HEX)
        col_line_bot = hex_to_rgb(COVER_BOTTOM_LINE_COLOR_HEX)

        px_per_pt_x = W / A4_W_PT
        px_per_pt_y = H / A4_H_PT
        pt_per_cm   = 72.0 / 2.54
        pt_per_mm   = 72.0 / 25.4
        px_per_cm_x = px_per_pt_x * pt_per_cm
        px_per_cm_y = px_per_pt_y * pt_per_cm
        px_per_mm   = px_per_pt_y * pt_per_mm  # svislé mm -> px (osa Y roste dolů)

        # --- pás a linky ---
        left  = int(round(COVER_SIDE_MARGIN_CM * px_per_cm_x))
        right = W - left
        y_top = int(round(COVER_BAND_TOP_CM    * px_per_cm_y))   # vzdálenost od horního okraje
        y_bot = int(round(COVER_BAND_BOTTOM_CM * px_per_cm_y))
        if y_bot < y_top:
            y_top, y_bot = y_bot, y_top
        band_h = max(1, y_bot - y_top)

        line_px = max(1, int(round(COVER_LINE_THICKNESS_PT * px_per_pt_y)))
        draw.line([(left, y_top), (right, y_top)], fill=col_line_top, width=line_px)
        draw.line([(left, y_bot), (right, y_bot)], fill=col_line_bot, width=line_px)

        # --- font helpery ---
        def load_font(size_pt: int):
            try:
                return ImageFont.truetype(PREVIEW_TTF or "DejaVuSans.ttf", size_pt)
            except Exception:
                return ImageFont.load_default()

        def text_w(s: str, f: ImageFont.FreeTypeFont) -> int:
            try:
                return draw.textlength(s, font=f)
            except Exception:
                bbox = draw.textbbox((0, 0), s, font=f)
                return bbox[2] - bbox[0]

        # --- NADPIS (wrap ≤ 2 řádky, auto-shrink, baseline + offset v mm) ---
        title = (self.title.strip() or "CENOVÁ NABÍDKA").upper()
        fs = COVER_TITLE_SIZE_PT
        min_fs = 22
        leading_factor = 1.12
        max_w = right - left

        def wrap_lines(text: str, fs_pt: int):
            f = load_font(fs_pt)
            words = text.split()
            lines, cur = [], ""
            for w in words:
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

        lines, f = wrap_lines(title, fs)
        asc, desc = f.getmetrics()
        line_h = math.ceil((asc + desc) * leading_factor)

        while (
            len(lines) > 2
            or any(text_w(L, f) > max_w for L in lines)
            or (len(lines) * line_h) > band_h
        ) and fs > min_fs:
            fs -= 1
            lines, f = wrap_lines(title, fs)
            asc, desc = f.getmetrics()
            line_h = math.ceil((asc + desc) * leading_factor)

        block_h   = len(lines) * line_h
        offset_px = int(round(COVER_TITLE_OFFSET_MM * px_per_mm))  # kladné = POSUN NAHORU (odečítáme)

        # vrchní hrana bloku uvnitř pásu (Y odshora), baseline = top + asc - offset
        top_y_block = y_top + (band_h - block_h) // 2
        baseline_y  = top_y_block + asc - offset_px

        for L in lines:
            x = left + (max_w - text_w(L, f)) // 2
            # Pillow default anchor je "lt" (left-top) – kreslíme v bodě baseline-asc
            draw.text((x, baseline_y - asc), L, fill=col_title, font=f)
            baseline_y += line_h

        # --- INFO BLOK (u spodního okraje, po baseline), datum nad ním ---
        f_info = load_font(COVER_INFO_SIZE_PT)
        asc_i, desc_i = f_info.getmetrics()
        line_h_info = math.ceil((asc_i + desc_i) * 1.15)

        info_left   = int(round(COVER_INFO_BLOCK_LEFT_CM   * px_per_cm_x))
        info_bottom = int(round(COVER_INFO_BLOCK_BOTTOM_CM * px_per_cm_y))

        info_lines = [ln for ln in (self.info_text or "").splitlines() if ln.strip()]
        total_info_h = len(info_lines) * line_h_info
        # umístit tak, aby spodní hrana bloku byla ve vzdálenosti info_bottom od spodku stránky
        y_start = H - info_bottom - total_info_h
        baseline = y_start + asc_i

        for ln in info_lines:
            draw.text((info_left, baseline - asc_i), ln, fill=col_title, font=f_info)
            baseline += line_h_info

        if self.use_today:
            date_str = english_date_upper() if self.date_style == "EN" else czech_date()
            gap_date = max(4, line_h_info // 3)
            date_baseline = y_start - gap_date
            if date_baseline > 0:
                draw.text((info_left, date_baseline - asc_i), date_str, fill=col_title, font=f_info)

        return img

    def _render_components_preview_pil(self, paths):
        """
        4 dlaždice uvnitř marginů v mm (jen pro segmentové stránky),
        přesný fill bez mezer, cover (ořez) na poměr inner_w : tile_h.
        """
        img = self._blank_a4()
        W, H = img.size

        # převody
        px_per_pt_x = W / A4_W_PT
        px_per_pt_y = H / A4_H_PT
        pt_per_mm   = 72.0 / 25.4
        px_per_mm_x = px_per_pt_x * pt_per_mm
        px_per_mm_y = px_per_pt_y * pt_per_mm

        # rozbal margin v pixelech
        def unpack_margin_mm_px(m):
            if isinstance(m, (list, tuple)) and len(m) == 4:
                ml, mt, mr, mb = m
            else:
                ml = mt = mr = mb = float(m)
            return (
                int(round(ml * px_per_mm_x)),
                int(round(mt * px_per_mm_y)),
                int(round(mr * px_per_mm_x)),
                int(round(mb * px_per_mm_y)),
            )

        ml_px, mt_px, mr_px, mb_px = unpack_margin_mm_px(COMPONENT_MARGIN_MM)

        inner_w = max(1, W - ml_px - mr_px)
        inner_h = max(1, H - mt_px - mb_px)

        # hrany 4 pásů přesně přes vnitřní výšku (rounded), aby nevznikla mezera
        edges = [mt_px + round(i * inner_h / SEGMENTS_PER_PAGE_FIXED) for i in range(SEGMENTS_PER_PAGE_FIXED + 1)]

        for i, pth in enumerate(paths):
            y0, y1 = edges[i], edges[i+1]
            tile_h = max(1, y1 - y0)

            try:
                im = Image.open(pth).convert("RGB")
            except Exception:
                im = Image.new("RGB", (2839, 1004), "lightgray")

            iw, ih = im.size
            target_ratio = inner_w / tile_h
            img_ratio = iw / ih

            # cover crop na poměr inner_w : tile_h
            if img_ratio > target_ratio:
                new_w = int(ih * target_ratio)
                x0 = max(0, (iw - new_w) // 2)
                box = (x0, 0, x0 + new_w, ih)
            else:
                new_h = int(iw / target_ratio)
                ycrop = max(0, (ih - new_h) // 2)
                box = (0, ycrop, iw, ycrop + new_h)

            # resize přesně do vnitřního boxu
            tile = im.crop(box).resize((inner_w, tile_h), Image.LANCZOS)
            img.paste(tile, (ml_px, y0))

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