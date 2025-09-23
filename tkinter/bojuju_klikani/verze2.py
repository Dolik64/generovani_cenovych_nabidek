import os
import sys
import math
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk, ImageOps, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor

APP_TITLE = "Tvorba cenové nabídky (cover dle šablony)"
# --- Nastavení: cesta k výchozí složce se segmenty (volitelné) ---
SEGMENT_POOL_DIR = r"/Users/jirka/Downloads/tvorba cenovych nabidek/python/aplikace na generovani/pool/segmenty"  # <- sem případně zadejte pevnou cestu (např. r"C:\projekty\segmenty")

# pevně 4 segmenty na stránku (dle zadání)
SEGMENTS_PER_PAGE_FIXED = 4

# rozměry a layout
MARGIN_CM = 2.0          # okraje pro seznam segmentů
GAP_CM = 0.5             # mezera mezi segmenty
PRICE_TOP_OFFSET_CM = 2  # „2 cm od horní hrany papíru“
PREVIEW_WIDTH_PX = 520   # šířka náhledu A4 (výška dopočtena)
A4_W_PT, A4_H_PT = A4    # 595.27 x 841.89 pt

# Styl titulní strany (viz obrázek)
COVER_TITLE_COLOR_HEX = "#2E6F82"   # tmavě petrolejová pro text i linky
COVER_LINE_THICKNESS_PT = 1
COVER_SIDE_MARGIN_CM = 1.2          # odsazení horizontálních linek a nadpisu od levého/pravého okraje
COVER_BAND_TOP_CM = 4.5             # svislá pozice horní linky od horní hrany
COVER_BAND_BOTTOM_CM = 5.7          # svislá pozice dolní linky od horní hrany
COVER_TITLE_SIZE_PT = 40            # velikost nadpisu
COVER_INFO_BLOCK_LEFT_CM = 1.5      # odsazení info bloku od levé hrany
COVER_INFO_BLOCK_BOTTOM_CM = 2.0    # odsazení info bloku od spodní hrany
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
    # Kvůli diakritice: zkuste mít v adresáři DejaVuSans.ttf (nebo změňte na vlastní TTF)
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
        self.thumb_imgtk = None  # Tkinter image cache

class QuoteBuilderApp(tk.Tk):
    def __init__(self, auto_dir=None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x820")

        self.font_name, self.preview_ttf = try_register_font()

        self.segments = []          # all loaded Segment objects
        self.selected_order = []    # list of indices into self.segments in user-defined order
        self.price_image_path = None

        self.margin_cm = MARGIN_CM
        self.gap_cm = GAP_CM

        # --- Cover fields ---
        self.cover_title = tk.StringVar(value="CENOVÁ NABÍDKA SIMULÁTORU")
        self.cover_info = tk.StringVar(value="Jiří Doležal\nNad Hrádkem 284\n25226 Kosoř")
        self.cover_date_style = tk.StringVar(value="EN")  # EN -> 'SEPTEMBER 23, 2025', CZ -> '23. 9. 2025'
        self.use_today = tk.BooleanVar(value=True)

        # UI
        self._build_ui()

        # Auto-load from fixed dir or CLI arg if provided
        initial_dir = auto_dir or (SEGMENT_POOL_DIR if SEGMENT_POOL_DIR.strip() else None)
        if initial_dir and os.path.isdir(initial_dir):
            self.load_segments_dir(initial_dir)

        # Prepare preview basis
        self._rebuild_preview_pages()

    def _build_ui(self):
        # Top controls bar
        top = tk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        tk.Button(top, text="Načíst složku se segmenty (PNG)", command=self.load_segments_dialog).pack(side=tk.LEFT)
        tk.Button(top, text="Načíst obrázek cenové tabulky", command=self.load_price_image).pack(side=tk.LEFT, padx=6)

        # Okraje a mezery (ponecháno jako nastavitelné)
        tk.Label(top, text="Okraj (cm):").pack(side=tk.LEFT, padx=(16, 4))
        self.spin_margin = tk.Spinbox(top, from_=0, to=5, increment=0.5, width=4, command=self.on_layout_changed)
        self.spin_margin.delete(0, tk.END)
        self.spin_margin.insert(0, f"{self.margin_cm}")
        self.spin_margin.pack(side=tk.LEFT)

        tk.Label(top, text="Mezera (cm):").pack(side=tk.LEFT, padx=(16, 4))
        self.spin_gap = tk.Spinbox(top, from_=0, to=3, increment=0.5, width=4, command=self.on_layout_changed)
        self.spin_gap.delete(0, tk.END)
        self.spin_gap.insert(0, f"{self.gap_cm}")
        self.spin_gap.pack(side=tk.LEFT)

        tk.Button(top, text="Export PDF…", command=self.export_pdf).pack(side=tk.RIGHT)

        # Second row: cover controls
        cover = tk.LabelFrame(self, text="Titulní strana")
        cover.pack(fill=tk.X, padx=8, pady=(0,8))

        tk.Label(cover, text="Nadpis:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        tk.Entry(cover, textvariable=self.cover_title, width=48).grid(row=0, column=1, sticky="we", padx=6, pady=4)

        tk.Label(cover, text="Blok adresy (multi-řádek):").grid(row=1, column=0, sticky="nw", padx=6, pady=4)
        tk.Entry(cover, textvariable=self.cover_info, width=48).grid(row=1, column=1, sticky="we", padx=6, pady=4)

        tk.Label(cover, text="Datum:").grid(row=0, column=2, sticky="e", padx=(18,4))
        self.combo_date = ttk.Combobox(cover, state="readonly", values=["EN", "CZ"], width=5, textvariable=self.cover_date_style)
        self.combo_date.grid(row=0, column=3, sticky="w", padx=(0,6))
        self.combo_date.bind("<<ComboboxSelected>>", lambda e: self._rebuild_preview_pages())

        tk.Checkbutton(cover, text="Použít dnešní datum", variable=self.use_today, command=self._rebuild_preview_pages).grid(row=0, column=4, sticky="w", padx=6)

        cover.grid_columnconfigure(1, weight=1)

        # Main panes
        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))

        # Left: gallery (scrollable)
        self.gallery_frame = tk.Frame(panes, borderwidth=1, relief=tk.GROOVE)
        panes.add(self.gallery_frame, weight=2)
        self._build_gallery()

        # Middle: selection and ordering
        mid = tk.Frame(panes, borderwidth=1, relief=tk.GROOVE)
        panes.add(mid, weight=1)
        self._build_selection(mid)

        # Right: preview
        right = tk.Frame(panes, borderwidth=1, relief=tk.GROOVE)
        panes.add(right, weight=3)
        self._build_preview(right)

    def _build_gallery(self):
        # Scrollable canvas with frame inside
        self.gallery_canvas = tk.Canvas(self.gallery_frame)
        self.gallery_scroll = ttk.Scrollbar(self.gallery_frame, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_inner = tk.Frame(self.gallery_canvas)

        self.gallery_inner.bind(
            "<Configure>", lambda e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all"))
        )
        self.gallery_canvas.create_window((0,0), window=self.gallery_inner, anchor="nw")
        self.gallery_canvas.configure(yscrollcommand=self.gallery_scroll.set)

        self.gallery_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.gallery_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_selection(self, parent):
        tk.Label(parent, text="Vybrané segmenty (pořadí) – na stránku se vejdou vždy 4").pack(anchor="w", padx=6, pady=(6,0))
        self.listbox = tk.Listbox(parent, height=20, selectmode=tk.SINGLE)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        btns = tk.Frame(parent)
        btns.pack(fill=tk.X, padx=6, pady=(0,6))
        tk.Button(btns, text="Nahoru", command=self.move_up).pack(side=tk.LEFT)
        tk.Button(btns, text="Dolů", command=self.move_down).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text="Odebrat", command=self.remove_selected).pack(side=tk.LEFT)

        bottom = tk.Frame(parent)
        bottom.pack(fill=tk.X, padx=6, pady=(0,6))
        tk.Button(bottom, text="Vybrat vše", command=self.select_all).pack(side=tk.LEFT)
        tk.Button(bottom, text="Zrušit výběr", command=self.clear_selection).pack(side=tk.LEFT, padx=6)

    def _build_preview(self, parent):
        tk.Label(parent, text="Náhled dokumentu").pack(anchor="w", padx=6, pady=(6,0))

        top = tk.Frame(parent)
        top.pack(fill=tk.X, padx=6, pady=4)
        tk.Label(top, text="Stránka:").pack(side=tk.LEFT)
        self.combo_page = ttk.Combobox(top, state="readonly", values=["1"], width=8)
        self.combo_page.current(0)
        self.combo_page.bind("<<ComboboxSelected>>", lambda e: self.show_preview_page())
        self.combo_page.pack(side=tk.LEFT, padx=6)

        self.preview_canvas = tk.Canvas(parent, width=PREVIEW_WIDTH_PX, height=int(PREVIEW_WIDTH_PX * (A4_H_PT/A4_W_PT)), bg="#f3f3f3")
        self.preview_canvas.pack(padx=6, pady=6)

        # backing image
        self.preview_imgtk = None
        self.preview_image_cache = []  # list of PIL images representing pages

    # ---------- Data loading ----------

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

        # load PNGs
        paths = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".png")]
        paths.sort()
        for p in paths:
            self.segments.append(Segment(p))

        if not self.segments:
            messagebox.showwarning("Prázdná složka", "Nebyly nalezeny žádné PNG soubory.")
            return

        self._render_gallery()
        self._rebuild_preview_pages()

    def _render_gallery(self):
        # Create thumb tiles (clickable)
        # Thumbs width 260px
        thumb_w = 260
        col_count = 2
        padx = pady = 6

        for idx, seg in enumerate(self.segments):
            # load thumb
            try:
                im = Image.open(seg.path)
                im.thumbnail((thumb_w, int(thumb_w*0.5)), Image.LANCZOS)
            except Exception:
                im = Image.new("RGB", (thumb_w, int(thumb_w*0.5)), "gray")

            border_color = "red" if seg.selected else "#dddddd"
            frame = tk.Frame(self.gallery_inner, bd=2, relief=tk.SOLID, highlightthickness=2, highlightbackground=border_color)
            frame.grid(row=idx // col_count, column=idx % col_count, padx=padx, pady=pady, sticky="n")

            seg.thumb_imgtk = ImageTk.PhotoImage(im)
            lbl = tk.Label(frame, image=seg.thumb_imgtk)
            lbl.pack()
            name = tk.Label(frame, text=seg.filename, wraplength=thumb_w)
            name.pack(pady=2)

            def make_cb(i=idx, fr=frame):
                return lambda e=None: self.toggle_segment(i, fr)
            frame.bind("<Button-1>", make_cb())
            lbl.bind("<Button-1>", make_cb())
            name.bind("<Button-1>", make_cb())

    def toggle_segment(self, idx, frame_widget=None):
        seg = self.segments[idx]
        seg.selected = not seg.selected

        # Border color
        if frame_widget:
            frame_widget.configure(highlightbackground=("red" if seg.selected else "#dddddd"))

        # maintain selected_order
        if seg.selected:
            self.selected_order.append(idx)
            self.listbox.insert(tk.END, self.segments[idx].filename)
        else:
            if idx in self.selected_order:
                pos = self.selected_order.index(idx)
                self.selected_order.pop(pos)
                self.listbox.delete(pos)

        self._rebuild_preview_pages()

    def select_all(self):
        # select any not selected
        for i, seg in enumerate(self.segments):
            if not seg.selected:
                seg.selected = True
                self.selected_order.append(i)
        self._refresh_gallery_borders()
        self._rebuild_listbox()
        self._rebuild_preview_pages()

    def clear_selection(self):
        for seg in self.segments:
            seg.selected = False
        self.selected_order.clear()
        self._refresh_gallery_borders()
        self._rebuild_listbox()
        self._rebuild_preview_pages()

    def _refresh_gallery_borders(self):
        # brute-force: rebuild gallery to refresh borders
        for w in self.gallery_inner.winfo_children():
            w.destroy()
        self._render_gallery()

    def _rebuild_listbox(self):
        self.listbox.delete(0, tk.END)
        for idx in self.selected_order:
            self.listbox.insert(tk.END, self.segments[idx].filename)

    def move_up(self):
        sel = self.listbox.curselection()
        if not sel: return
        i = sel[0]
        if i == 0: return
        self.selected_order[i-1], self.selected_order[i] = self.selected_order[i], self.selected_order[i-1]
        self._rebuild_listbox()
        self.listbox.select_set(i-1)
        self._rebuild_preview_pages()

    def move_down(self):
        sel = self.listbox.curselection()
        if not sel: return
        i = sel[0]
        if i >= len(self.selected_order)-1: return
        self.selected_order[i+1], self.selected_order[i] = self.selected_order[i], self.selected_order[i+1]
        self._rebuild_listbox()
        self.listbox.select_set(i+1)
        self._rebuild_preview_pages()

    def remove_selected(self):
        sel = self.listbox.curselection()
        if not sel: return
        i = sel[0]
        idx_to_remove = self.selected_order[i]
        self.segments[idx_to_remove].selected = False
        self.selected_order.pop(i)
        self._refresh_gallery_borders()
        self._rebuild_listbox()
        self._rebuild_preview_pages()

    def load_price_image(self):
        p = filedialog.askopenfilename(title="Vyberte obrázek s cenovou tabulkou", filetypes=[("Obrázky","*.png;*.jpg;*.jpeg;*.webp;*.tif;*.tiff")])
        if p:
            self.price_image_path = p
            self._rebuild_preview_pages()

    # ---------- Preview logic ----------

    def on_layout_changed(self):
        try:
            self.margin_cm = float(self.spin_margin.get())
        except ValueError:
            self.margin_cm = MARGIN_CM
        try:
            self.gap_cm = float(self.spin_gap.get())
        except ValueError:
            self.gap_cm = GAP_CM
        self._rebuild_preview_pages()

    def _rebuild_preview_pages(self):
        # Build PIL images representing pages: cover + component pages + price page
        pages = []

        # Cover
        pages.append(self._render_cover_preview())

        # Components pages
        n = len(self.selected_order)
        spp = SEGMENTS_PER_PAGE_FIXED
        total_comp_pages = math.ceil(n / spp) if n>0 else 0

        for p in range(total_comp_pages):
            start = p * spp
            end = min(start + spp, n)
            idxs = self.selected_order[start:end]
            pages.append(self._render_components_preview(idxs))

        # Price page (always last)
        pages.append(self._render_price_preview())

        self.preview_image_cache = pages
        self.combo_page["values"] = [str(i+1) for i in range(len(pages))]
        self.combo_page.current(0)
        self.show_preview_page()

    def _make_blank_a4(self):
        # Produce a white A4 @ 96 DPI-ish for nicer preview scaling
        ratio = A4_H_PT / A4_W_PT
        w = PREVIEW_WIDTH_PX
        h = int(w * ratio)
        return Image.new("RGB", (w, h), "white")

    def _cover_color_rgb(self):
        # Convert hex to RGB tuple for PIL
        hx = COVER_TITLE_COLOR_HEX.lstrip("#")
        return tuple(int(hx[i:i+2],16) for i in (0,2,4))

    def _get_preview_font(self, size_pt):
        # try to use the same TTF as PDF for preview
        if self.preview_ttf and os.path.exists(self.preview_ttf):
            try:
                return ImageFont.truetype(self.preview_ttf, size_pt)
            except Exception:
                pass
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size_pt)
        except Exception:
            return ImageFont.load_default()

    def _render_cover_preview(self):
        img = self._make_blank_a4()
        draw = ImageDraw.Draw(img)

        W, H = img.size
        col = self._cover_color_rgb()

        # positions
        left = int(COVER_SIDE_MARGIN_CM * (W / (A4_W_PT / cm)))
        right = W - left
        y_top = int(COVER_BAND_TOP_CM * (H / (A4_H_PT / cm)))
        y_bot = int(COVER_BAND_BOTTOM_CM * (H / (A4_H_PT / cm)))

        # lines
        draw.line([(left, y_top), (right, y_top)], fill=col, width=max(1,int(COVER_LINE_THICKNESS_PT/2)))
        draw.line([(left, y_bot), (right, y_bot)], fill=col, width=max(1,int(COVER_LINE_THICKNESS_PT/2)))

        # title (uppercase)
        title = (self.cover_title.get().strip() or "CENOVÁ NABÍDKA").upper()
        font = self._get_preview_font(COVER_TITLE_SIZE_PT)
        tw, th = draw.textbbox((0,0), title, font=font)[2:4]
        # baseline vertically centered between lines
        y_text = (y_top + y_bot - th)//2
        draw.text((left, y_text), title, fill=col, font=font)

        # info block bottom-left
        info_font = self._get_preview_font(COVER_INFO_SIZE_PT)
        info_left = int(COVER_INFO_BLOCK_LEFT_CM * (W / (A4_W_PT / cm)))
        info_bottom = int(COVER_INFO_BLOCK_BOTTOM_CM * (H / (A4_H_PT / cm)))
        # date
        if self.use_today.get():
            date_str = english_date_upper() if self.cover_date_style.get()=="EN" else czech_date()
            draw.text((info_left, H - info_bottom - COVER_INFO_SIZE_PT*2), date_str, fill=col, font=info_font)
            y_start = H - info_bottom - COVER_INFO_SIZE_PT
        else:
            y_start = H - info_bottom - 0
        # multi-line info
        for i, line in enumerate(self.cover_info.get().splitlines()):
            draw.text((info_left, y_start + i*(COVER_INFO_SIZE_PT+4)), line, fill=col, font=info_font)

        return img

    def _render_components_preview(self, idxs):
        img = self._make_blank_a4()
        draw = ImageDraw.Draw(img)

        W, H = img.size
        # Přepočet cm -> pixel náhledu (poměrově dle šířky)
        margin_px = int(self.margin_cm * (W / (A4_W_PT / cm)))
        gap_px = int(self.gap_cm * (W / (A4_W_PT / cm)))

        usable_w = W - 2*margin_px
        usable_h = H - 2*margin_px
        spp = SEGMENTS_PER_PAGE_FIXED if idxs else SEGMENTS_PER_PAGE_FIXED

        # target height tak, aby spp položek + mezery vyšly do usable_h
        total_gap = gap_px * max(0, spp-1)
        max_item_h = max(10, (usable_h - total_gap) // spp)

        y = margin_px
        for idx in idxs:
            seg = self.segments[idx]
            try:
                im = Image.open(seg.path)
            except Exception:
                im = Image.new("RGB", (2839, 1004), "lightgray")
            # scale to fit width usable_w, ale limit i výškou
            w0, h0 = im.size
            scale_w = usable_w / w0
            scale_h = max_item_h / h0
            scale = min(scale_w, scale_h)
            nw, nh = int(w0*scale), int(h0*scale)
            im_resized = im.resize((nw, nh), Image.LANCZOS)
            # paste centered horizontally
            x = margin_px + (usable_w - nw)//2
            img.paste(im_resized, (x, y))
            y += nh + gap_px

        # rámeček stránky (jen v náhledu)
        draw.rectangle([0,0,W-1,H-1], outline="#dddddd")
        return img

    def _render_price_preview(self):
        img = self._make_blank_a4()
        draw = ImageDraw.Draw(img)

        W, H = img.size
        top_offset_px = int(PRICE_TOP_OFFSET_CM * (H / (A4_H_PT / cm)))
        margin_px = int(self.margin_cm * (W / (A4_W_PT / cm)))
        max_w = W - 2*margin_px
        max_h = H - top_offset_px - margin_px

        if self.price_image_path and os.path.exists(self.price_image_path):
            try:
                im = Image.open(self.price_image_path)
            except Exception:
                im = Image.new("RGB", (1200,800), "lightgray")
        else:
            # placeholder
            im = Image.new("RGB", (1200,800), "white")
            pd = ImageDraw.Draw(im)
            font = self._get_preview_font(36)
            text = "Cenová tabulka (obrázek nenahrán)"
            tw, th = pd.textbbox((0,0), text, font=font)[2:4]
            pd.text(((1200-tw)//2, (800-th)//2), text, fill="black", font=font)

        w0, h0 = im.size
        scale = min(max_w / w0, max_h / h0, 1.0)
        nw, nh = int(w0*scale), int(h0*scale)
        im_resized = im.resize((nw, nh), Image.LANCZOS)

        x = (W - nw)//2
        y = top_offset_px
        img.paste(im_resized, (x, y))

        draw.rectangle([0,0,W-1,H-1], outline="#dddddd")
        return img

    def show_preview_page(self):
        if not self.preview_image_cache:
            return
        try:
            idx = int(self.combo_page.get()) - 1
        except Exception:
            idx = 0
        idx = max(0, min(idx, len(self.preview_image_cache)-1))
        pil_img = self.preview_image_cache[idx]
        # convert to imgtk
        imgtk = ImageTk.PhotoImage(pil_img)
        self.preview_imgtk = imgtk
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0,0, anchor="nw", image=imgtk)

    # ---------- PDF export ----------

    def export_pdf(self):
        out = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF","*.pdf")], title="Uložit PDF")
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

        # Titulní strana (stylizovaná)
        col = HexColor(COVER_TITLE_COLOR_HEX)
        left = COVER_SIDE_MARGIN_CM * cm
        right = W - left
        y_top = H - (COVER_BAND_TOP_CM * cm)
        y_bot = H - (COVER_BAND_BOTTOM_CM * cm)

        c.setStrokeColor(col)
        c.setLineWidth(COVER_LINE_THICKNESS_PT)
        c.line(left, y_top, right, y_top)
        c.line(left, y_bot, right, y_bot)

        # title
        title = (self.cover_title.get().strip() or "CENOVÁ NABÍDKA").upper()
        c.setFillColor(col)
        t = c.beginText()
        t.setTextOrigin(left, (y_top + y_bot)/2 - (COVER_TITLE_SIZE_PT*0.35))
        t.setFont(self.font_name, COVER_TITLE_SIZE_PT)
        try:
            t.setCharSpace(1.2)  # jemné rozestupy
        except Exception:
            pass
        t.textLine(title)
        c.drawText(t)

        # info block bottom-left
        info_x = COVER_INFO_BLOCK_LEFT_CM * cm
        info_y_base = COVER_INFO_BLOCK_BOTTOM_CM * cm
        c.setFont(self.font_name, COVER_INFO_SIZE_PT)
        # date
        if self.use_today.get():
            date_str = english_date_upper() if self.cover_date_style.get()=="EN" else czech_date()
            c.drawString(info_x, info_y_base + 3*(COVER_INFO_SIZE_PT+2), date_str)
            start_y = info_y_base + 2*(COVER_INFO_SIZE_PT+2)
        else:
            start_y = info_y_base
        for i, line in enumerate(self.cover_info.get().splitlines()):
            c.drawString(info_x, start_y + i*(COVER_INFO_SIZE_PT+2), line)

        c.showPage()

        # Strany se segmenty – vždy 4/stranu
        n = len(self.selected_order)
        spp = SEGMENTS_PER_PAGE_FIXED
        if n > 0:
            total_pages = math.ceil(n / spp)

            usable_w = W - 2*margin
            usable_h = H - 2*margin
            total_gap = gap * max(0, spp-1)
            max_item_h = max(10, (usable_h - total_gap) / spp)

            for p in range(total_pages):
                start = p * spp
                end = min(start + spp, n)
                y = H - margin  # start from top margin, go down
                for idx in self.selected_order[start:end]:
                    seg = self.segments[idx]
                    im = Image.open(seg.path)
                    w0, h0 = im.size
                    scale = min(usable_w / w0, max_item_h / h0)
                    nw, nh = w0*scale, h0*scale
                    # center horizontally
                    x = (W - nw) / 2
                    y -= nh
                    # draw
                    img_reader = ImageReader(im.resize((int(nw), int(nh)), Image.LANCZOS))
                    c.drawImage(img_reader, x, y, width=nw, height=nh, preserveAspectRatio=False, mask='auto')
                    y -= gap
                c.showPage()

        # Poslední strana: cenová tabulka
        y_top = H - PRICE_TOP_OFFSET_CM * cm
        max_w = W - 2*margin
        max_h = (H - (PRICE_TOP_OFFSET_CM * cm)) - margin
        if self.price_image_path and os.path.exists(self.price_image_path):
            im = Image.open(self.price_image_path)
        else:
            # placeholder pokud chybí
            im = Image.new("RGB", (1200,800), "white")
            dr = ImageDraw.Draw(im)
            try:
                f = ImageFont.truetype(self.preview_ttf or "DejaVuSans.ttf", 36)
            except Exception:
                f = ImageFont.load_default()
            text = "Cenová tabulka (obrázek nenahrán)"
            tw, th = dr.textbbox((0,0), text, font=f)[2:4]
            dr.text(((1200-tw)//2, (800-th)//2), text, fill="black", font=f)

        w0, h0 = im.size
        scale = min(max_w / w0, max_h / h0, 1.0)
        nw, nh = w0*scale, h0*scale
        x = (W - nw) / 2
        y = y_top - nh

        img_reader_price = ImageReader(im.resize((int(nw), int(nh)), Image.LANCZOS))
        c.drawImage(img_reader_price, x, y, width=nw, height=nh, preserveAspectRatio=False, mask='auto')

        # Žádná čísla stran ani patičky se nekreslí
        c.showPage()
        c.save()

if __name__ == "__main__":
    # Volitelně: cesta ke složce se segmenty jako 1. argumentem CLI
    # python quote_builder.py "C:\cesta\k\segmentum"
    auto_dir = sys.argv[1] if len(sys.argv) > 1 else None
    app = QuoteBuilderApp(auto_dir=auto_dir)
    app.mainloop()