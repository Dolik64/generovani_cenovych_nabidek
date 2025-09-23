# -*- coding: utf-8 -*-
import math
import os
from pathlib import Path
from typing import List
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor

from config import (
    A4_W_PT, A4_H_PT, FONT_NAME, PREVIEW_TTF,
    SEGMENTS_PER_PAGE_FIXED, PRICE_TOP_OFFSET_CM,
    COVER_TITLE_COLOR_HEX, COVER_LINE_THICKNESS_PT, COVER_SIDE_MARGIN_CM,
    COVER_BAND_TOP_CM, COVER_BAND_BOTTOM_CM, COVER_TITLE_SIZE_PT,
    COVER_INFO_BLOCK_LEFT_CM, COVER_INFO_BLOCK_BOTTOM_CM, COVER_INFO_SIZE_PT,
    czech_date, english_date_upper
)

def export_pdf(
    out_path: str,
    order_paths: List[str],
    margin_cm: float,
    gap_cm: float,
    title_text: str,
    info_lines_text: str,
    date_style: str,
    use_today: bool,
    price_image_path: str | None,
):
    c = pdfcanvas.Canvas(out_path, pagesize=A4)
    W, H = A4_W_PT, A4_H_PT
    margin = margin_cm * cm
    gap = gap_cm * cm

    # Titulní strana
    col = HexColor(COVER_TITLE_COLOR_HEX)
    left = COVER_SIDE_MARGIN_CM * cm
    right = W - left
    y_top = H - (COVER_BAND_TOP_CM * cm)
    y_bot = H - (COVER_BAND_BOTTOM_CM * cm)
    c.setStrokeColor(col); c.setLineWidth(COVER_LINE_THICKNESS_PT)
    c.line(left, y_top, right, y_top); c.line(left, y_bot, right, y_bot)

    title = (title_text.strip() or "CENOVÁ NABÍDKA").upper()
    c.setFillColor(col); t = c.beginText()
    t.setTextOrigin(left, (y_top + y_bot)/2 - (COVER_TITLE_SIZE_PT*0.35))
    t.setFont(FONT_NAME, COVER_TITLE_SIZE_PT)
    try: t.setCharSpace(1.2)
    except Exception: pass
    t.textLine(title); c.drawText(t)

    info_x = COVER_INFO_BLOCK_LEFT_CM * cm
    info_y_base = COVER_INFO_BLOCK_BOTTOM_CM * cm
    c.setFont(FONT_NAME, COVER_INFO_SIZE_PT)
    if use_today:
        date_str = english_date_upper() if date_style == "EN" else czech_date()
        c.drawString(info_x, info_y_base + 3*(COVER_INFO_SIZE_PT+2), date_str)
        start_y = info_y_base + 2*(COVER_INFO_SIZE_PT+2)
    else:
        start_y = info_y_base
    for i, line in enumerate(info_lines_text.splitlines()):
        c.drawString(info_x, start_y + i*(COVER_INFO_SIZE_PT+2), line)

    c.showPage()

    # Komponenty 4/stranu
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

    # Poslední stránka – ceník
    y_top = H - PRICE_TOP_OFFSET_CM * cm
    max_w = W - 2*margin
    max_h = (H - (PRICE_TOP_OFFSET_CM * cm)) - margin
    if price_image_path and os.path.exists(price_image_path):
        im = Image.open(price_image_path).convert("RGB")
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