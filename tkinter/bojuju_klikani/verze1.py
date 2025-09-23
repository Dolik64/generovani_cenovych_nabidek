import os
import sys
import math
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

APP_TITLE = "Tvorba cenové nabídky (prototyp)"
SEGMENTS_PER_PAGE_DEFAULT = 4
MARGIN_CM = 2.0          # okraje pro seznam segmentů
GAP_CM = 0.5             # mezera mezi segmenty
PRICE_TOP_OFFSET_CM = 2  # „2 cm od horní hrany papíru“
PREVIEW_WIDTH_PX = 520   # šířka náhledu A4 (výška dopočtena)
A4_W_PT, A4_H_PT = A4    # 595.27 x 841.89 pt

def czech_date(d=None):
    if d is None:
        d = datetime.date.today()
    return d.strftime("%-d. %-m. %Y") if sys.platform != "win32" else d.strftime("%#d. %#m. %Y")

def try_register_font():
    # Kvůli diakritice: zkuste mít v adresáři DejaVuSans.ttf
    ttf_path = os.path.join(os.path.dirname(__file__), "DejaVuSans.ttf")
    if os.path.exists(ttf_path):
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", ttf_path))
            return "DejaVuSans"
        except Exception:
            pass
    return "Helvetica"

class Segment:
    def __init__(self, path):
        self.path = path
        self.filename = os.path.basename(path)
        self.selected = False
        self.thumb_imgtk = None  # Tkinter image cache

class QuoteBuilderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x780")

        self.font_name = try_register_font()

        self.segments = []          # all loaded Segment objects
        self.selected_order = []    # list of indices into self.segments in user-defined order
        self.price_image_path = None

        self.segments_per_page = SEGMENTS_PER_PAGE_DEFAULT
        self.margin_cm = MARGIN_CM
        self.gap_cm = GAP_CM

        # UI
        self._build_ui()

        # Prepare preview basis
        self._rebuild_preview_pages()

    def _build_ui(self):
        # Top controls bar
        top = tk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        tk.Button(top, text="Načíst složku se segmenty (PNG)", command=self.load_segments_dir).pack(side=tk.LEFT)
        tk.Button(top, text="Načíst obrázek cenové tabulky", command=self.load_price_image).pack(side=tk.LEFT, padx=6)

        tk.Label(top, text="Segmentů/stranu:").pack(side=tk.LEFT, padx=(16, 4))
        self.spin_per_page = tk.Spinbox(top, from_=1, to=10, width=4, command=self.on_layout_changed)
        self.spin_per_page.delete(0, tk.END)
        self.spin_per_page.insert(0, str(self.segments_per_page))
        self.spin_per_page.pack(side=tk.LEFT)

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

        tk.Label(top, text="Nadpis titulní strany:").pack(side=tk.LEFT, padx=(16, 4))
        self.entry_title = tk.Entry(top, width=28)
        self.entry_title.insert(0, "Cenová nabídka")
        self.entry_title.pack(side=tk.LEFT, padx=(0, 8))

        self.var_use_today = tk.BooleanVar(value=True)
        tk.Checkbutton(top, text="Použít dnešní datum", variable=self.var_use_today, command=self._rebuild_preview_pages).pack(side=tk.LEFT)

        tk.Button(top, text="Export PDF…", command=self.export_pdf).pack(side=tk.RIGHT)

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
        tk.Label(parent, text="Vybrané segmenty (pořadí)").pack(anchor="w", padx=6, pady=(6,0))
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

    def load_segments_dir(self):
        d = filedialog.askdirectory(title="Vyberte složku se segmenty (PNG)")
        if not d:
            return
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
            self.segments_per_page = int(self.spin_per_page.get())
        except ValueError:
            self.segments_per_page = SEGMENTS_PER_PAGE_DEFAULT
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
        spp = max(1, self.segments_per_page)
        total_comp_pages = math.ceil(n / spp) if n>0 else 1

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

    def _render_cover_preview(self):
        img = self._make_blank_a4()
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(img)
        # Try to load a TTF for preview text
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 36)
            font2 = ImageFont.truetype("DejaVuSans.ttf", 22)
        except Exception:
            font = ImageFont.load_default()
            font2 = ImageFont.load_default()

        title = self.entry_title.get().strip() or "Cenová nabídka"
        date_str = czech_date() if self.var_use_today.get() else ""

        # center title
        W,H = img.size
        tw, th = draw.textsize(title, font=font)
        draw.text(((W-tw)//2, H//3), title, fill="black", font=font)

        if date_str:
            dw, dh = draw.textsize(date_str, font=font2)
            draw.text(((W-dw)//2, H//3 + th + 20), date_str, fill="black", font=font2)

        return img

    def _render_components_preview(self, idxs):
        img = self._make_blank_a4()
        draw = ImageDraw.Draw(img)

        W, H = img.size
        margin_px = int(self.margin_cm * (W / (A4_W_PT / cm)))  # scale approx by width
        gap_px = int(self.gap_cm * (W / (A4_W_PT / cm)))

        usable_w = W - 2*margin_px
        usable_h = H - 2*margin_px
        spp = len(idxs) if len(idxs)>0 else self.segments_per_page

        # target height so that spp items + gaps fit into usable_h
        total_gap = gap_px * max(0, spp-1)
        max_item_h = max(10, (usable_h - total_gap) // spp)

        y = margin_px
        for idx in idxs:
            seg = self.segments[idx]
            try:
                im = Image.open(seg.path)
            except Exception:
                im = Image.new("RGB", (2839, 1004), "lightgray")
            # scale to fit width usable_w, but also limit by max_item_h
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

        # draw page frame
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
            from PIL import ImageFont
            im = Image.new("RGB", (1200,800), "white")
            pd = ImageDraw.Draw(im)
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", 36)
            except Exception:
                font = ImageFont.load_default()
            text = "Cenová tabulka (obrázek nenahrán)"
            tw, th = pd.textsize(text, font=font)
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
        if not self.segments:
            if not messagebox.askyesno("Bez segmentů", "Nebyly načteny žádné segmenty. Vygenerovat PDF jen s titulní a cenovou stranou?"):
                return

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

        # Cover
        title = self.entry_title.get().strip() or "Cenová nabídka"
        date_str = czech_date() if self.var_use_today.get() else ""
        c.setFont(self.font_name, 28)
        c.drawCentredString(W/2, H*0.62, title)
        if date_str:
            c.setFont(self.font_name, 14)
            c.drawCentredString(W/2, H*0.62 - 28, date_str)
        c.showPage()

        # Components
        n = len(self.selected_order)
        spp = max(1, self.segments_per_page)
        total_pages = math.ceil(n / spp) if n>0 else 1

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
                # save PIL to temporary in-memory
                from io import BytesIO
                buf = BytesIO()
                im.resize((int(nw), int(nh)), Image.LANCZOS).save(buf, format="PNG")
                buf.seek(0)
                c.drawImage(buf, x, y, width=nw, height=nh, preserveAspectRatio=False, mask='auto')
                buf.close()
                y -= gap
            c.showPage()

        # Price page
        y_top = H - PRICE_TOP_OFFSET_CM * cm
        max_w = W - 2*margin
        max_h = (H - (PRICE_TOP_OFFSET_CM * cm)) - margin
        if self.price_image_path and os.path.exists(self.price_image_path):
            im = Image.open(self.price_image_path)
        else:
            # placeholder if missing
            im = Image.new("RGB", (1200,800), "white")
            from PIL import ImageDraw, ImageFont
            dr = ImageDraw.Draw(im)
            try:
                f = ImageFont.truetype("DejaVuSans.ttf", 36)
            except Exception:
                f = ImageFont.load_default()
            text = "Cenová tabulka (obrázek nenahrán)"
            tw, th = dr.textsize(text, font=f)
            dr.text(((1200-tw)//2, (800-th)//2), text, fill="black", font=f)

        w0, h0 = im.size
        scale = min(max_w / w0, max_h / h0, 1.0)
        nw, nh = w0*scale, h0*scale
        x = (W - nw) / 2
        y = y_top - nh

        from io import BytesIO
        buf = BytesIO()
        im.resize((int(nw), int(nh)), Image.LANCZOS).save(buf, format="PNG")
        buf.seek(0)
        c.drawImage(buf, x, y, width=nw, height=nh, preserveAspectRatio=False, mask='auto')
        buf.close()

        c.showPage()
        c.save()

if __name__ == "__main__":
    app = QuoteBuilderApp()
    app.mainloop()