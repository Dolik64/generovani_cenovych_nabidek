# -*- coding: utf-8 -*-
import sys
import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---- App / cesty ----
APP_TITLE = "Tvorba cenové nabídky (PySide6)"
SEGMENT_POOL_DIR = Path("/Users/jirka/Downloads/tvorba cenovych nabidek/python/aplikace na generovani/pool/segmenty")

# ---- Layout ----
SEGMENTS_PER_PAGE_FIXED = 4
MARGIN_CM_DEFAULT = 2.0
GAP_CM_DEFAULT = 0.5
PRICE_TOP_OFFSET_CM = 2

# A4
A4_W_PT, A4_H_PT = A4

# ---- Titulní strana ----
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
    # Windows nemá %-d / %-m
    return d.strftime("%-d. %-m. %Y") if sys.platform != "win32" else d.strftime("%#d. %#m. %Y")

def english_date_upper(d=None):
    if d is None:
        d = datetime.date.today()
    return d.strftime("%B %d, %Y").upper()

def try_register_font():
    """
    Zkusí registrovat DejaVuSans.ttf ležící vedle appky, jinak vrátí Helvetica.
    Vrací (font_name, ttf_path | None).
    """
    ttf_path = Path(__file__).with_name("DejaVuSans.ttf")
    if ttf_path.exists():
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", str(ttf_path)))
            return "DejaVuSans", str(ttf_path)
        except Exception:
            pass
    return "Helvetica", None

# Předregistruj (nevadí volat víckrát)
FONT_NAME, PREVIEW_TTF = try_register_font()