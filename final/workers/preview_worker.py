# -*- coding: utf-8 -*-
import math
import os
from typing import List
from PySide6.QtCore import QRunnable, Qt, QMetaObject, Q_ARG
from PIL import Image, ImageDraw, ImageFont

from config import (
    A4_W_PT, A4_H_PT, SEGMENTS_PER_PAGE_FIXED, PRICE_TOP_OFFSET_CM,
    COVER_TITLE_COLOR_HEX, COVER_LINE_THICKNESS_PT, COVER_SIDE_MARGIN_CM,
    COVER_BAND_TOP_CM, COVER_BAND_BOTTOM_CM, COVER_TITLE_SIZE_PT,
    COVER_INFO_BLOCK_LEFT_CM, COVER_INFO_BLOCK_BOTTOM_CM, COVER_INFO_SIZE_PT,
    PREVIEW_TTF, czech_date, english_date_upper
)
from reportlab.lib.units import cm

class PreviewWorker(QRunnable):
    """
    Staví PIL náhledové stránky na pozadí a předá list PIL.Image zpět do GUI vlákna.
    """
    def __init__(self, order_paths: List[str], margin_cm: float, gap_cm: float,
                 price_path: str, title: str, info_text: str,
                 date_style: str, use_today: bool,
                 receiver: object, slot_name: str, width_px: int = 900):
        super().__init__()
        self.order_paths = order_paths
        self.margin_cm = margin_cm
        self.gap_cm = gap_cm
        self.price_path = price_path
        self.title = title
        self.info_text = info_text
        self.date_style = date_style
        self.use_today = use_today
        self.receiver = receiver
        self.slot_name = slot_name
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

        QMetaObject.invokeMethod(self.receiver, self.slot_name, Qt.QueuedConnection, Q_ARG(object, pages))

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
        th = ImageDraw.Draw(Image.new("RGB",(1,1))).textbbox((0,0), title, font=font)[3]
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
        for i, line in enumerate((self.info_text or "").splitlines()):
            draw.text((info_left, y_start + i*(COVER_INFO_SIZE_PT+4)), line, fill=col, font=info_font)
        return img

    def _render_components_preview_pil(self, paths):
        img = self._blank_a4()
        draw = ImageDraw.Draw(img)
        W, H = img.size
        margin_px = int(self.margin_cm * (W / (A4_W_PT / cm)))
        gap_px = int(self.gap_cm * (W / (A4_W_PT / cm)))
        usable_w = W - 2*margin_px
        usable_h = H - 2*margin_px
        total_gap = gap_px * 3  # 4 na stranu => 3 mezery
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

    def _render_price_preview_pil(self):
        img = self._blank_a4()
        draw = ImageDraw.Draw(img)
        W, H = img.size
        margin_px = int(self.margin_cm * (W / (A4_W_PT / cm)))
        top_offset_px = int(PRICE_TOP_OFFSET_CM * (H / (A4_H_PT / cm)))
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
            text = "Cenová tabulka (obrázek nenahrán)"
            tw, th = pd.textbbox((0,0), text, font=font)[2:4]
            pd.text(((1200-tw)//2, (800-th)//2), text, fill="black", font=font)

        w0, h0 = im.size
        scale = min(max_w / w0, max_h / h0, 1.0)
        nw, nh = int(w0*scale), int(h0*scale)
        im2 = im.resize((nw, nh), Image.BILINEAR)
        x = (W - nw)//2
        y = top_offset_px
        img.paste(im2, (x, y))
        draw.rectangle([0,0,W-1,H-1], outline="#dddddd")
        return img