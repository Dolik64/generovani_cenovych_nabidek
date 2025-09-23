import os
import sys
import math
import datetime
import threading
import queue

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor

APP_TITLE = "Tvorba cenové nabídky (Canvas galerie)"
SEGMENT_POOL_DIR = r"/Users/jirka/Downloads/tvorba cenovych nabidek/python/aplikace na generovani/pool/segmenty"
SEGMENTS_PER_PAGE_FIXED = 4

# Layout
MARGIN_CM = 2.0
GAP_CM = 0.5
PRICE_TOP_OFFSET_CM = 2
PREVIEW_WIDTH_PX = 520
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

# Preview tuning
DEBOUNCE_MS = 120
RESIZE_BUCKET = 8

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

class Segment:
    def __init__(self, path):
        self.path = path
        self.filename = os.path.basename(path)
        self.selected = False
        self.thumb_imgtk = None
        # Canvas dlaždice:
        self.tile = None        # tk.Canvas
        self.border_id = None   # id obdélníku rámečku

class ImageCache:
    def __init__(self):
        self._thumbs = {}   # (idx, w) -> PIL.Image
        self._resized = {}  # (idx, w, h) -> PIL.Image

    @staticmethod
    def _bucket(v):
        return int(max(1, round(v / RESIZE_BUCKET) * RESIZE_BUCKET))

    def get_thumb(self, idx, loader, target_w):
        key = (idx, self._bucket(target_w))
        if key in self._thumbs:
            return self._thumbs[key]
        im = loader()
        im = im.convert("RGB")
        im.thumbnail((target_w, target_w // 2), Image.BILINEAR)
        self._thumbs[key] = im
        return im

    def get_resized(self, idx, loader, target_w, target_h):
        bw, bh = self._bucket(target_w), self._bucket(target_h)
        key = (idx, bw, bh)
        if key in self._resized:
            return self._resized[key]
        im = loader().convert("RGB")
        w0, h0 = im.size
        scale = min(target_w / w0, target_h / h0)
        nw, nh = max(1, int(w0 * scale)), max(1, int(h0 * scale))
        im2 = im.resize((nw, nh), Image.BILINEAR)
        self._resized[key] = im2
        return im2

class QuoteBuilderApp(tk.Tk):
    def __init__(self, auto_dir=None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x820")

        self.font_name, self.preview_ttf = try_register_font()

        self.segments = []
        self.selected_order = []
        self.price_image_path = None

        self.margin_cm = MARGIN_CM
        self.gap_cm = GAP_CM

        # Cover fields
        self.cover_title = tk.StringVar(value="CENOVÁ NABÍDKA SIMULÁTORU")
        self.cover_info = tk.StringVar(value="Jiří Doležal\nNad Hrádkem 284\n25226 Kosoř")
        self.cover_date_style = tk.StringVar(value="EN")
        self.use_today = tk.BooleanVar(value=True)

        # Preview infra
        self.preview_pages = []
        self.preview_imgtk = None
        self.preview_job_id = 0
        self.preview_timer = None
        self.image_cache = ImageCache()

        # UI
        self._build_ui()

        initial_dir = auto_dir or (SEGMENT_POOL_DIR if SEGMENT_POOL_DIR.strip() else None)
        if initial_dir and os.path.isdir(initial_dir):
            self.load_segments_dir(initial_dir)

        self._schedule_preview_build()

    # ---------- UI ----------
    def _build_ui(self):
        top = tk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        tk.Button(top, text="Načíst složku se segmenty (PNG)", command=self.load_segments_dialog).pack(side=tk.LEFT)
        tk.Button(top, text="Načíst obrázek cenové tabulky", command=self.load_price_image).pack(side=tk.LEFT, padx=6)

        tk.Label(top, text="Okraj (cm):").pack(side=tk.LEFT, padx=(16, 4))
        self.spin_margin = tk.Spinbox(top, from_=0, to=5, increment=0.5, width=4, command=self._on_layout_changed)
        self.spin_margin.delete(0, tk.END); self.spin_margin.insert(0, f"{self.margin_cm}"); self.spin_margin.pack(side=tk.LEFT)

        tk.Label(top, text="Mezera (cm):").pack(side=tk.LEFT, padx=(16, 4))
        self.spin_gap = tk.Spinbox(top, from_=0, to=3, increment=0.5, width=4, command=self._on_layout_changed)
        self.spin_gap.delete(0, tk.END); self.spin_gap.insert(0, f"{self.gap_cm}"); self.spin_gap.pack(side=tk.LEFT)

        tk.Button(top, text="Export PDF…", command=self.export_pdf).pack(side=tk.RIGHT)

        cover = tk.LabelFrame(self, text="Titulní strana")
        cover.pack(fill=tk.X, padx=8, pady=(0,8))
        tk.Label(cover, text="Nadpis:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        tk.Entry(cover, textvariable=self.cover_title, width=48).grid(row=0, column=1, sticky="we", padx=6, pady=4)
        tk.Label(cover, text="Blok adresy (multi-řádek):").grid(row=1, column=0, sticky="nw", padx=6, pady=4)
        tk.Entry(cover, textvariable=self.cover_info, width=48).grid(row=1, column=1, sticky="we", padx=6, pady=4)
        tk.Label(cover, text="Datum:").grid(row=0, column=2, sticky="e", padx=(18,4))
        self.combo_date = ttk.Combobox(cover, state="readonly", values=["EN", "CZ"], width=5, textvariable=self.cover_date_style)
        self.combo_date.grid(row=0, column=3, sticky="w", padx=(0,6))
        self.combo_date.bind("<<ComboboxSelected>>", lambda e: self._schedule_preview_build())
        tk.Checkbutton(cover, text="Použít dnešní datum", variable=self.use_today, command=self._schedule_preview_build).grid(row=0, column=4, sticky="w", padx=6)
        cover.grid_columnconfigure(1, weight=1)

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))

        self.gallery_frame = tk.Frame(panes, borderwidth=1, relief=tk.GROOVE); panes.add(self.gallery_frame, weight=2)
        self._build_gallery()

        mid = tk.Frame(panes, borderwidth=1, relief=tk.GROOVE); panes.add(mid, weight=1)
        self._build_selection(mid)

        right = tk.Frame(panes, borderwidth=1, relief=tk.GROOVE); panes.add(right, weight=3)
        self._build_preview(right)

    def _build_gallery(self):
        self.gallery_canvas = tk.Canvas(self.gallery_frame)
        self.gallery_scroll = ttk.Scrollbar(self.gallery_frame, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_inner = tk.Frame(self.gallery_canvas)
        self.gallery_inner.bind("<Configure>", lambda e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))
        self.gallery_canvas.create_window((0,0), window=self.gallery_inner, anchor="nw")
        self.gallery_canvas.configure(yscrollcommand=self.gallery_scroll.set)
        self.gallery_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.gallery_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_selection(self, parent):
        tk.Label(parent, text="Vybrané segmenty (pořadí) – 4/stranu").pack(anchor="w", padx=6, pady=(6,0))
        self.listbox = tk.Listbox(parent, height=20, selectmode=tk.SINGLE)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        btns = tk.Frame(parent); btns.pack(fill=tk.X, padx=6, pady=(0,6))
        tk.Button(btns, text="Nahoru", command=self.move_up).pack(side=tk.LEFT)
        tk.Button(btns, text="Dolů", command=self.move_down).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text="Odebrat", command=self.remove_selected).pack(side=tk.LEFT)
        bottom = tk.Frame(parent); bottom.pack(fill=tk.X, padx=6, pady=(0,6))
        tk.Button(bottom, text="Vybrat vše", command=self.select_all).pack(side=tk.LEFT)
        tk.Button(bottom, text="Zrušit výběr", command=self.clear_selection).pack(side=tk.LEFT, padx=6)

    def _build_preview(self, parent):
        tk.Label(parent, text="Náhled dokumentu").pack(anchor="w", padx=6, pady=(6,0))
        top = tk.Frame(parent); top.pack(fill=tk.X, padx=6, pady=4)
        tk.Label(top, text="Stránka:").pack(side=tk.LEFT)
        self.combo_page = ttk.Combobox(top, state="readonly", values=["1"], width=8)
        self.combo_page.current(0)
        self.combo_page.bind("<<ComboboxSelected>>", lambda e: self.show_preview_page())
        self.combo_page.pack(side=tk.LEFT, padx=6)
        self.preview_canvas = tk.Canvas(parent, width=PREVIEW_WIDTH_PX, height=int(PREVIEW_WIDTH_PX*(A4_H_PT/A4_W_PT)), bg="#f3f3f3")
        self.preview_canvas.pack(padx=6, pady=6)

    # ---------- Data ----------
    def load_segments_dialog(self):
        d = filedialog.askdirectory(title="Vyberte složku se segmenty (PNG)")
        if d:
            self.load_segments_dir(d)

    def load_segments_dir(self, d):
        # reset
        self.segments.clear()
        self.selected_order.clear()
        self.listbox.delete(0, tk.END)
        for w in self.gallery_inner.winfo_children():
            w.destroy()
        self.image_cache = ImageCache()

        paths = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".png")]
        paths.sort()
        for p in paths:
            self.segments.append(Segment(p))

        if not self.segments:
            messagebox.showwarning("Prázdná složka", "Nebyly nalezeny žádné PNG soubory.")
            return

        self._render_gallery()
        self._schedule_preview_build()

    def _render_gallery(self):
        thumb_w = 260
        col_count = 2
        padx = pady = 6

        for idx, seg in enumerate(self.segments):
            def loader(path=seg.path):
                return Image.open(path)

            pil_thumb = self.image_cache.get_thumb(idx, loader, thumb_w)
            seg.thumb_imgtk = ImageTk.PhotoImage(pil_thumb)

            tile_w = thumb_w + 14
            tile_h = pil_thumb.height + 40

            tile = tk.Canvas(
                self.gallery_inner,
                width=tile_w,
                height=tile_h,
                highlightthickness=0,
                bd=0,
                bg="white",
                cursor="hand2"
            )
            tile.grid(row=idx // col_count, column=idx % col_count, padx=padx, pady=pady, sticky="n")
            seg.tile = tile

            tag = f"tile{idx}"

            border_id = tile.create_rectangle(
                1, 1, tile_w - 2, tile_h - 2,
                outline=("red" if seg.selected else "#dddddd"),
                width=2,
                tags=(tag,)
            )
            seg.border_id = border_id

            tile.create_image(7, 7, anchor="nw", image=seg.thumb_imgtk, tags=(tag,))
            tile.create_text(7, pil_thumb.height + 14, anchor="nw", text=seg.filename, width=thumb_w, tags=(tag,))

            def on_tile_click(event, i=idx, t=tile, bid=border_id):
                self.toggle_segment(i)
                color = "red" if self.segments[i].selected else "#dddddd"
                t.itemconfigure(bid, outline=color)
                return "break"

            tile.tag_bind(tag, "<Button-1>", on_tile_click)

    def _on_layout_changed(self):
        try:
            self.margin_cm = float(self.spin_margin.get())
        except ValueError:
            self.margin_cm = MARGIN_CM
        try:
            self.gap_cm = float(self.spin_gap.get())
        except ValueError:
            self.gap_cm = GAP_CM
        self._schedule_preview_build()

    # ---------- Selection ops ----------
    def toggle_segment(self, idx, _frame_widget=None):
        seg = self.segments[idx]
        seg.selected = not seg.selected

        # okamžitá vizuální odezva (Canvas rámeček)
        if seg.tile and seg.border_id is not None:
            seg.tile.itemconfigure(seg.border_id, outline=("red" if seg.selected else "#dddddd"))

        if seg.selected:
            if idx not in self.selected_order:
                self.selected_order.append(idx)
                self.listbox.insert(tk.END, seg.filename)
        else:
            if idx in self.selected_order:
                pos = self.selected_order.index(idx)
                self.selected_order.pop(pos)
                self.listbox.delete(pos)

        self._schedule_preview_build()

    def select_all(self):
        for i, seg in enumerate(self.segments):
            if not seg.selected:
                seg.selected = True
                if i not in self.selected_order:
                    self.selected_order.append(i)
            if seg.tile and seg.border_id is not None:
                seg.tile.itemconfigure(seg.border_id, outline="red")
        self._rebuild_listbox()
        self._schedule_preview_build()

    def clear_selection(self):
        for seg in self.segments:
            seg.selected = False
            if seg.tile and seg.border_id is not None:
                seg.tile.itemconfigure(seg.border_id, outline="#dddddd")
        self.selected_order.clear()
        self._rebuild_listbox()
        self._schedule_preview_build()

    def _rebuild_listbox(self):
        self.listbox.delete(0, tk.END)
        for idx in self.selected_order:
            self.listbox.insert(tk.END, self.segments[idx].filename)

    def move_up(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        i = sel[0]
        if i == 0:
            return
        self.selected_order[i - 1], self.selected_order[i] = self.selected_order[i], self.selected_order[i - 1]
        self._rebuild_listbox()
        self.listbox.select_set(i - 1)
        self._schedule_preview_build()

    def move_down(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        i = sel[0]
        if i >= len(self.selected_order) - 1:
            return
        self.selected_order[i + 1], self.selected_order[i] = self.selected_order[i], self.selected_order[i + 1]
        self._rebuild_listbox()
        self.listbox.select_set(i + 1)
        self._schedule_preview_build()

    def remove_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        i = sel[0]
        idx_to_remove = self.selected_order[i]
        seg = self.segments[idx_to_remove]
        seg.selected = False
        if seg.tile and seg.border_id is not None:
            seg.tile.itemconfigure(seg.border_id, outline="#dddddd")
        self.selected_order.pop(i)
        self._rebuild_listbox()
        self._schedule_preview_build()

    def load_price_image(self):
        p = filedialog.askopenfilename(title="Vyberte obrázek s cenovou tabulkou", filetypes=[("Obrázky","*.png;*.jpg;*.jpeg;*.webp;*.tif;*.tiff")])
        if p:
            self.price_image_path = p
            self._schedule_preview_build()

    # ---------- Preview async pipeline ----------
    def _schedule_preview_build(self):
        if self.preview_timer:
            try:
                self.after_cancel(self.preview_timer)
            except Exception:
                pass
        self.preview_timer = self.after(DEBOUNCE_MS, self._start_preview_job)

    def _start_preview_job(self):
        self.preview_job_id += 1
        job_id = self.preview_job_id
        self.config(cursor="watch")
        threading.Thread(target=self._build_preview_pages_worker, args=(job_id,), daemon=True).start()

    def _build_preview_pages_worker(self, job_id):
        pages = self._build_preview_pages_pil()
        self.after(0, self._accept_preview, job_id, pages)

    def _build_preview_pages_pil(self):
        pages = []
        pages.append(self._render_cover_preview_pil())
        n = len(self.selected_order)
        spp = SEGMENTS_PER_PAGE_FIXED
        total_comp_pages = math.ceil(n / spp) if n > 0 else 0
        for p in range(total_comp_pages):
            idxs = self.selected_order[p * spp: p * spp + spp]
            pages.append(self._render_components_preview_pil(idxs))
        pages.append(self._render_price_preview_pil())
        return pages

    def _accept_preview(self, job_id, pages):
        if job_id != self.preview_job_id:
            return
        self.preview_pages = pages
        self.combo_page["values"] = [str(i + 1) for i in range(len(pages))]
        self.combo_page.current(0)
        self.show_preview_page()
        self.config(cursor="")

    def _make_blank_a4(self):
        ratio = A4_H_PT / A4_W_PT
        w = PREVIEW_WIDTH_PX
        h = int(w * ratio)
        return Image.new("RGB", (w, h), "white")

    def _cover_color_rgb(self):
        hx = COVER_TITLE_COLOR_HEX.lstrip("#")
        return tuple(int(hx[i:i+2], 16) for i in (0, 2, 4))

    def _get_preview_font(self, size_pt):
        if self.preview_ttf and os.path.exists(self.preview_ttf):
            try:
                return ImageFont.truetype(self.preview_ttf, size_pt)
            except Exception:
                pass
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size_pt)
        except Exception:
            return ImageFont.load_default()

    # --- PIL renderers ---
    def _render_cover_preview_pil(self):
        img = self._make_blank_a4()
        draw = ImageDraw.Draw(img)
        W, H = img.size
        col = self._cover_color_rgb()
        left = int(COVER_SIDE_MARGIN_CM * (W / (A4_W_PT / cm)))
        right = W - left
        y_top = int(COVER_BAND_TOP_CM * (H / (A4_H_PT / cm)))
        y_bot = int(COVER_BAND_BOTTOM_CM * (H / (A4_H_PT / cm)))
        draw.line([(left, y_top), (right, y_top)], fill=col, width=max(1, int(COVER_LINE_THICKNESS_PT / 2)))
        draw.line([(left, y_bot), (right, y_bot)], fill=col, width=max(1, int(COVER_LINE_THICKNESS_PT / 2)))
        title = (self.cover_title.get().strip() or "CENOVÁ NABÍDKA").upper()
        font = self._get_preview_font(COVER_TITLE_SIZE_PT)
        tw, th = draw.textbbox((0, 0), title, font=font)[2:4]
        y_text = (y_top + y_bot - th) // 2
        draw.text((left, y_text), title, fill=col, font=font)
        info_font = self._get_preview_font(COVER_INFO_SIZE_PT)
        info_left = int(COVER_INFO_BLOCK_LEFT_CM * (W / (A4_W_PT / cm)))
        info_bottom = int(COVER_INFO_BLOCK_BOTTOM_CM * (H / (A4_H_PT / cm)))
        if self.use_today.get():
            date_str = english_date_upper() if self.cover_date_style.get() == "EN" else czech_date()
            draw.text((info_left, H - info_bottom - COVER_INFO_SIZE_PT * 2), date_str, fill=col, font=info_font)
            y_start = H - info_bottom - COVER_INFO_SIZE_PT
        else:
            y_start = H - info_bottom
        for i, line in enumerate(self.cover_info.get().splitlines()):
            draw.text((info_left, y_start + i * (COVER_INFO_SIZE_PT + 4)), line, fill=col, font=info_font)
        return img

    def _render_components_preview_pil(self, idxs):
        img = self._make_blank_a4()
        draw = ImageDraw.Draw(img)
        W, H = img.size
        margin_px = int(self.margin_cm * (W / (A4_W_PT / cm)))
        gap_px = int(self.gap_cm * (W / (A4_W_PT / cm)))
        usable_w = W - 2 * margin_px
        usable_h = H - 2 * margin_px
        total_gap = gap_px * max(0, SEGMENTS_PER_PAGE_FIXED - 1)
        max_item_h = max(10, (usable_h - total_gap) // SEGMENTS_PER_PAGE_FIXED)
        y = margin_px
        for idx in idxs:
            seg = self.segments[idx]
            def loader(path=seg.path):
                return Image.open(path)
            im_resized = self.image_cache.get_resized(idx, loader, usable_w, max_item_h)
            x = margin_px + (usable_w - im_resized.size[0]) // 2
            img.paste(im_resized, (x, y))
            y += im_resized.size[1] + gap_px
        draw.rectangle([0, 0, W - 1, H - 1], outline="#dddddd")
        return img

    def _render_price_preview_pil(self):
        img = self._make_blank_a4()
        draw = ImageDraw.Draw(img)
        W, H = img.size
        top_offset_px = int(PRICE_TOP_OFFSET_CM * (H / (A4_H_PT / cm)))
        margin_px = int(self.margin_cm * (W / (A4_W_PT / cm)))
        max_w = W - 2 * margin_px
        max_h = H - top_offset_px - margin_px
        if self.price_image_path and os.path.exists(self.price_image_path):
            try:
                im = Image.open(self.price_image_path).convert("RGB")
            except Exception:
                im = Image.new("RGB", (1200, 800), "lightgray")
        else:
            im = Image.new("RGB", (1200, 800), "white")
            pd = ImageDraw.Draw(im)
            font = self._get_preview_font(36)
            text = "Cenová tabulka (obrázek nenahrán)"
            tw, th = pd.textbbox((0, 0), text, font=font)[2:4]
            pd.text(((1200 - tw) // 2, (800 - th) // 2), text, fill="black", font=font)
        w0, h0 = im.size
        scale = min(max_w / w0, max_h / h0, 1.0)
        nw, nh = int(w0 * scale), int(h0 * scale)
        im_resized = im.resize((nw, nh), Image.BILINEAR)
        x = (W - nw) // 2
        y = top_offset_px
        img.paste(im_resized, (x, y))
        draw.rectangle([0, 0, W - 1, H - 1], outline="#dddddd")
        return img

    def show_preview_page(self):
        if not self.preview_pages:
            return
        try:
            idx = int(self.combo_page.get()) - 1
        except Exception:
            idx = 0
        idx = max(0, min(idx, len(self.preview_pages) - 1))
        pil_img = self.preview_pages[idx]
        self.preview_imgtk = ImageTk.PhotoImage(pil_img)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=self.preview_imgtk)

    # ---------- PDF ----------
    def export_pdf(self):
        out = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")], title="Uložit PDF")
        if not out:
            return
        try:
            self._make_pdf(out)
            messagebox.showinfo("Hotovo", f"PDF bylo vytvořeno:\n{out}")
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodařilo se vytvořit PDF:\n{e}")

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

        title = (self.cover_title.get().strip() or "CENOVÁ NABÍDKA").upper()
        c.setFillColor(col)
        t = c.beginText()
        t.setTextOrigin(left, (y_top + y_bot) / 2 - (COVER_TITLE_SIZE_PT * 0.35))
        t.setFont(self.font_name, COVER_TITLE_SIZE_PT)
        try:
            t.setCharSpace(1.2)
        except Exception:
            pass
        t.textLine(title)
        c.drawText(t)

        info_x = COVER_INFO_BLOCK_LEFT_CM * cm
        info_y_base = COVER_INFO_BLOCK_BOTTOM_CM * cm
        c.setFont(self.font_name, COVER_INFO_SIZE_PT)
        if self.use_today.get():
            date_str = english_date_upper() if self.cover_date_style.get() == "EN" else czech_date()
            c.drawString(info_x, info_y_base + 3 * (COVER_INFO_SIZE_PT + 2), date_str)
            start_y = info_y_base + 2 * (COVER_INFO_SIZE_PT + 2)
        else:
            start_y = info_y_base
        for i, line in enumerate(self.cover_info.get().splitlines()):
            c.drawString(info_x, start_y + i * (COVER_INFO_SIZE_PT + 2), line)

        c.showPage()

        n = len(self.selected_order)
        spp = SEGMENTS_PER_PAGE_FIXED
        if n > 0:
            total_pages = math.ceil(n / spp)
            usable_w = W - 2 * margin
            usable_h = H - 2 * margin
            total_gap = gap * max(0, spp - 1)
            max_item_h = max(10, (usable_h - total_gap) / spp)
            for p in range(total_pages):
                start = p * spp
                end = min(start + spp, n)
                y = H - margin
                for idx in self.selected_order[start:end]:
                    seg = self.segments[idx]
                    im = Image.open(seg.path).convert("RGB")
                    w0, h0 = im.size
                    scale = min(usable_w / w0, max_item_h / h0)
                    nw, nh = int(w0 * scale), int(h0 * scale)
                    x = (W - nw) / 2
                    y -= nh
                    img_reader = ImageReader(im.resize((nw, nh), Image.LANCZOS))
                    c.drawImage(img_reader, x, y, width=nw, height=nh, preserveAspectRatio=False, mask='auto')
                    y -= gap
                c.showPage()

        y_top = H - PRICE_TOP_OFFSET_CM * cm
        max_w = W - 2 * margin
        max_h = (H - (PRICE_TOP_OFFSET_CM * cm)) - margin
        if self.price_image_path and os.path.exists(self.price_image_path):
            im = Image.open(self.price_image_path).convert("RGB")
        else:
            im = Image.new("RGB", (1200, 800), "white")
            dr = ImageDraw.Draw(im)
            try:
                f = ImageFont.truetype(self.preview_ttf or "DejaVuSans.ttf", 36)
            except Exception:
                f = ImageFont.load_default()
            text = "Cenová tabulka (obrázek nenahrán)"
            tw, th = dr.textbbox((0, 0), text, font=f)[2:4]
            dr.text(((1200 - tw) // 2, (800 - th) // 2), text, fill="black", font=f)

        w0, h0 = im.size
        scale = min(max_w / w0, max_h / h0, 1.0)
        nw, nh = int(w0 * scale), int(h0 * scale)
        x = (W - nw) / 2
        y = y_top - nh
        img_reader_price = ImageReader(im.resize((nw, nh), Image.LANCZOS))
        c.drawImage(img_reader_price, x, y, width=nw, height=nh, preserveAspectRatio=False, mask='auto')

        c.showPage()
        c.save()

if __name__ == "__main__":
    auto_dir = sys.argv[1] if len(sys.argv) > 1 else None
    app = QuoteBuilderApp(auto_dir=auto_dir)
    app.mainloop()