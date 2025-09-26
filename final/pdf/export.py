# -*- coding: utf-8 -*-
import math
import os
from typing import List

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor


from reportlab.pdfbase import pdfmetrics

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
    COVER_INFO_BLOCK_LEFT_CM, COVER_INFO_BLOCK_BOTTOM_CM, COVER_INFO_SIZE_PT, COVER_TITLE_OFFSET_MM,
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
    
    pt_per_mm = 72.0 / 25.4
    offset_pt = COVER_TITLE_OFFSET_MM * pt_per_mm  # + nahoru, - dolů

        # === Titulní strana ======================================================
    col = HexColor(COVER_TITLE_COLOR_HEX)

    left_pt = COVER_SIDE_MARGIN_CM * pt_per_cm
    right_pt = W - left_pt
    y_top_pt = H - (COVER_BAND_TOP_CM * pt_per_cm)        # horní linka pásu (vyšší Y)
    y_bot_pt = H - (COVER_BAND_BOTTOM_CM * pt_per_cm)     # dolní linka pásu (nižší Y)
    band_h = max(1.0, y_top_pt - y_bot_pt)                # výška pásu

    # Linky pásu
    c.setStrokeColor(col)
    c.setLineWidth(COVER_LINE_THICKNESS_PT)
    c.line(left_pt, y_top_pt, right_pt, y_top_pt)
    c.line(left_pt, y_bot_pt, right_pt, y_bot_pt)

    # --- Nadpis: wrap (max 2 řádky) + auto-shrink + centrování ---
    title = (title_text.strip() or "CENOVÁ NABÍDKA").upper()
    max_w = right_pt - left_pt
    leading_factor = 1.12
    fs = COVER_TITLE_SIZE_PT
    min_fs = 22

    def wrap_lines(text, fs_pt):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if c.stringWidth(test, FONT_NAME, fs_pt) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def block_metrics(fs_pt):
        asc = pdfmetrics.getAscent(FONT_NAME)  * fs_pt / 1000.0
        dsc = abs(pdfmetrics.getDescent(FONT_NAME)) * fs_pt / 1000.0
        line_h = (asc + dsc) * leading_factor
        return asc, dsc, line_h

    lines = wrap_lines(title, fs)
    asc, dsc, line_h = block_metrics(fs)

    while (
        len(lines) > 2
        or any(c.stringWidth(L, FONT_NAME, fs) > max_w for L in lines)
        or (len(lines) * line_h) > band_h
    ) and fs > min_fs:
        fs -= 1
        lines = wrap_lines(title, fs)
        asc, dsc, line_h = block_metrics(fs)

    block_h = len(lines) * line_h
    top_y = y_bot_pt + (band_h - block_h) / 2.0        # horní okraj bloků textu
    baseline_y = top_y + asc + offset_pt               # baseline první řádky = top + ascent

    c.setFillColor(col)
    for L in lines:
        c.setFont(FONT_NAME, fs)
        line_w = c.stringWidth(L, FONT_NAME, fs)
        x = left_pt + (max_w - line_w) / 2.0           # horizontální střed pásu
        c.drawString(x, baseline_y, L)
        baseline_y += line_h

    # --- Spodní blok: adresa + (volitelně) datum nad adresou ---
    info_x = COVER_INFO_BLOCK_LEFT_CM * pt_per_cm
    info_y_base = COVER_INFO_BLOCK_BOTTOM_CM * pt_per_cm
    fs_info = COVER_INFO_SIZE_PT
    leading_info = fs_info * 1.15
    gap_date = 6

    info_lines = [ln for ln in info_lines_text.splitlines() if ln.strip()]
    y_info = info_y_base
    for ln in info_lines:
        c.setFont(FONT_NAME, fs_info)
        c.drawString(info_x, y_info, ln)
        y_info += leading_info

    if use_today:
        c.setFont(FONT_NAME, fs_info)
        date_str = english_date_upper() if date_style == "EN" else czech_date()
        c.drawString(info_x, y_info + gap_date, date_str)

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