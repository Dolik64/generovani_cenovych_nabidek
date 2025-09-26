# -*- coding: utf-8 -*-
import math
import os
from typing import List

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor

from config import (
    # Rozměry A4 v bodech
    A4_W_PT, A4_H_PT,
    # Fonty pro PDF / náhled
    FONT_NAME, PREVIEW_TTF,
    # Logika dokumentu
    SEGMENTS_PER_PAGE_FIXED, PRICE_TOP_OFFSET_CM,
    # Titulní strana
    COVER_TITLE_COLOR_HEX, COVER_LINE_THICKNESS_PT, COVER_SIDE_MARGIN_CM,
    COVER_BAND_TOP_CM, COVER_BAND_BOTTOM_CM, COVER_TITLE_SIZE_PT,
    COVER_INFO_BLOCK_LEFT_CM, COVER_INFO_BLOCK_BOTTOM_CM, COVER_INFO_SIZE_PT,
    # Datumové helpery
    czech_date, english_date_upper,
    # Pevná šířka screenshotu ceníku (v cm)
    PRICE_IMAGE_WIDTH_CM,
)

def export_pdf(
    out_path: str,
    order_paths: List[str],
    margin_cm: float,      # ignorováno (komponenty jedou edge-to-edge)
    gap_cm: float,         # ignorováno
    title_text: str,
    info_lines_text: str,
    date_style: str,
    use_today: bool,
    price_image_path: str | None,
):
    """
    Export PDF:
      - Titulní strana dle cm-konstant v config.py
      - Stránky komponent: 4 „dlaždice“ na výšku, edge-to-edge, cover ořez (bez deformace)
      - Poslední strana: screenshot ceníku s horním odsazením PRICE_TOP_OFFSET_CM
        a pevnou šířkou PRICE_IMAGE_WIDTH_CM (výška se dopočítá; když by přesáhla,
        zmenší se šířka/výška úměrně). Obrázek se NEpřevzorkovává – vkládá se
        v plném rozlišení pro minimální ztráty kvality.
    """
    c = pdfcanvas.Canvas(out_path, pagesize=A4)
    W, H = A4_W_PT, A4_H_PT  # body (1 pt = 1/72")
    pt_per_cm = 72.0 / 2.54

    # === Titulní strana ======================================================
    col = HexColor(COVER_TITLE_COLOR_HEX)

    left_pt = COVER_SIDE_MARGIN_CM * pt_per_cm
    right_pt = W - left_pt
    y_top_pt = H - (COVER_BAND_TOP_CM * pt_per_cm)
    y_bot_pt = H - (COVER_BAND_BOTTOM_CM * pt_per_cm)

    c.setStrokeColor(col)
    c.setLineWidth(COVER_LINE_THICKNESS_PT)
    c.line(left_pt, y_top_pt, right_pt, y_top_pt)
    c.line(left_pt, y_bot_pt, right_pt, y_bot_pt)

    title = (title_text.strip() or "CENOVÁ NABÍDKA").upper()
    c.setFillColor(col)
    t = c.beginText()
    t.setTextOrigin(left_pt, (y_top_pt + y_bot_pt)/2 - (COVER_TITLE_SIZE_PT*0.35))
    t.setFont(FONT_NAME, COVER_TITLE_SIZE_PT)
    try:
        t.setCharSpace(1.2)
    except Exception:
        pass
    t.textLine(title)
    c.drawText(t)

    info_x = COVER_INFO_BLOCK_LEFT_CM * pt_per_cm
    info_y_base = COVER_INFO_BLOCK_BOTTOM_CM * pt_per_cm
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

    # === Komponentové stránky: 4 dlaždice, edge-to-edge, cover ==============
    if order_paths:
        spp = SEGMENTS_PER_PAGE_FIXED  # 4
        total_pages = math.ceil(len(order_paths) / spp)
        cell_h_pt = H / spp                       # výška dlaždice v bodech
        target_ratio = W / cell_h_pt              # poměr w:h dlaždice

        for p in range(total_pages):
            start = p * spp
            end = min(start + spp, len(order_paths))
            y_top = H
            for path in order_paths[start:end]:
                im = Image.open(path).convert("RGB")
                iw, ih = im.size
                img_ratio = iw / ih

                # cover ořez do poměru W : cell_h_pt (poměr nezávislý na jednotkách)
                if img_ratio > target_ratio:
                    new_w = int(ih * target_ratio)
                    x0 = max(0, (iw - new_w) // 2)
                    box = (x0, 0, x0 + new_w, ih)
                else:
                    new_h = int(iw / target_ratio)
                    y0 = max(0, (ih - new_h) // 2)
                    box = (0, y0, iw, y0 + new_h)

                tile = im.crop(box)  # bez resize – ReportLab škáluje při vykreslení
                img_reader = ImageReader(tile)
                y_top -= cell_h_pt
                c.drawImage(img_reader, 0, y_top, width=W, height=cell_h_pt,
                            preserveAspectRatio=False, mask='auto')
            c.showPage()

    # === Cenová stránka: pevná šířka v cm, horní odsazení, bez re-samplingu ==
    top_offset_pt = PRICE_TOP_OFFSET_CM * pt_per_cm
    target_w_pt   = PRICE_IMAGE_WIDTH_CM * pt_per_cm
    max_h_pt      = H - top_offset_pt

    # Načtení screenshotu (PNG doporučeno kvůli ostrosti textu)
    if price_image_path and os.path.exists(price_image_path):
        im = Image.open(price_image_path).convert("RGB")
    else:
        # Placeholder, když obrázek není k dispozici
        im = Image.new("RGB", (1200, 800), "white")
        dr = ImageDraw.Draw(im)
        try:
            f = ImageFont.truetype(PREVIEW_TTF or "DejaVuSans.ttf", 36)
        except Exception:
            f = ImageFont.load_default()
        txt = "Cenová tabulka (obrázek nenahrán)"
        tw, th = dr.textbbox((0, 0), txt, font=f)[2:4]
        dr.text(((1200 - tw) // 2, (800 - th) // 2), txt, fill="black", font=f)

    w0, h0 = im.size  # pixely

    # Výška v bodech při pevné šířce (poměr stran)
    height_pt = (h0 / w0) * target_w_pt

    # Když by výška přesáhla dostupný prostor pod horním odsazením,
    # zmenši úměrně i šířku (stále bez re-samplingu originálu).
    if height_pt > max_h_pt:
        scale = max_h_pt / height_pt
        width_pt = target_w_pt * scale
        height_pt = max_h_pt
    else:
        width_pt = target_w_pt

    # Vlož originální bitmapu v plném rozlišení, jen ji „vykresli“ na daný box.
    img_reader_price = ImageReader(im)
    x = (W - width_pt) / 2
    y = H - top_offset_pt - height_pt
    c.drawImage(img_reader_price, x, y, width=width_pt, height=height_pt,
                preserveAspectRatio=False, mask='auto')

    c.showPage()
    c.save()