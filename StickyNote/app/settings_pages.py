"""Settings pages, redesigned (2026-11-28, the user's pick from the mockups): every page opened from
the Settings list has one shape. Its name and a one-line description under an icon, what it sets
inside a clear card, and a preview card wherever the setting changes how something looks.

A page is made the first time it is opened (or asked for by name: ``pages[key]``, or one of its
widgets: PAGE_ATTRS), not with the list: Settings opens faster and holds only what was used.
SettingsView (ui_views) takes this in; ``sync`` and ``recolor`` there run each made page's own.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from datetime import date, datetime
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageTk

import texts
import version
import winapi
from store import BACKUPS_KEPT, CUSTOM_COLORS, SNAP_GAPS
from texts import tr
from ui_common import (GLYPH, ICON_BOX, MARK_CONTRAST, PALETTE, TEXT_CONTRAST, UI_FONT, Colors, FlatButton,
                       FontPicker, NumberBox, Slider, Stepper, Tooltip, _finish_typing_first, _mix, accent_color,
                       contrast, dot_photo, fit_text, hero_photo, keycap_photo, luminance, paint_glyph, readable,
                       ui_font)

PAGE_KEYS = ("set_color", "set_font", "set_default_color", "set_theme_color", "set_transparency",
             "set_snap", "set_minimize", "set_date_format", "set_keys", "set_folder", "set_update")
PAGE_SUBTITLES = {"set_minimize": "help_minimize_short"}     # (its long help became the option rows)
HERO_PX = 34                    # a page's round icon
SWATCH_PX = 26                  # a colour page's swatches
KEYCAP_PX = 10                  # the text on a keycap
KEY_GROUPS = (                  # the Keys page: its keys in cards by what they are for
    ("keys_group_write", ("Ctrl+B · I · U · T", "Ctrl+Shift+L", "Ctrl+Shift+C", "Ctrl+V", "Ctrl+PgUp · PgDn")),
    ("keys_group_window", ("Ctrl+N", "Ctrl+Shift+N", "Ctrl+W", "Ctrl+Shift+T", "Ctrl+D")),
    ("keys_group_list", ("Esc", "↑↓ · Enter")),
)
MIN_STYLES = ("bar", "fold", "sticker")
UPDATE_ICONS = {"latest": "", "available": "", "error": "", "checking": "",
                "downloading": "", "installing": ""}


def _key_parts(combo: str) -> list[str]:
    """"Ctrl+Shift+N" -> Ctrl, Shift, N; "Ctrl+B · I · U · T" -> Ctrl, B, I, U, T."""
    out = []
    for piece in combo.split(" · "):
        out += [p for p in piece.split("+") if p]
    return out


def _middle_cut(text: str, room: int, measure) -> str:
    """``text`` cut in the middle with … to ``room`` px (a path keeps its drive and its folder)."""
    if measure(text) <= room:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        k = (lo + hi + 1) // 2
        head, tail = text[: (k + 1) // 2], text[len(text) - k // 2:] if k // 2 else ""
        if measure(head + "…" + tail) <= room:
            lo = k
        else:
            hi = k - 1
    head, tail = text[: (lo + 1) // 2], text[len(text) - lo // 2:] if lo // 2 else ""
    return head + "…" + tail


class _Pages(dict):
    """key -> its page; a page not made yet is made when asked for (``pages[key]``)."""

    def __init__(self, make):
        super().__init__()
        self._make = make

    def __missing__(self, key):
        page = self._make(key)
        if page is None:
            raise KeyError(key)
        return page


class SettingsPages:
    # the widgets a page owns: asked for by name, the page is made (older callers and tests)
    PAGE_ATTRS = {
        "alpha": "set_transparency", "alpha_box": "set_transparency", "alpha_unit": "set_transparency",
        "font_picker": "set_font", "size_box": "set_font",
        "date_rows": "set_date_format", "snap_buttons": "set_snap", "snap_unit": "set_snap",
        "min_rows": "set_minimize", "folder_path": "set_folder", "key_rows": "set_keys",
        "update_check": "set_update", "update_status": "set_update", "update_notes": "set_update",
        "update_now": "set_update", "update_later": "set_update", "update_box": "set_update",
        "update_buttons": "set_update", "update_elsewhere": "set_update",
    }

    def __getattr__(self, name):
        key = SettingsPages.PAGE_ATTRS.get(name)
        if key is None or "pages" not in self.__dict__:
            raise AttributeError(name)
        self.pages[key]
        try:
            return self.__dict__[name]
        except KeyError:
            raise AttributeError(name) from None

    # -- the frame of every page
    def _init_pages(self):
        self.rows, self.palettes, self.warnings = [], {}, {}
        self.pages = _Pages(self._make_page)
        self.page_syncs: dict = {}              # key -> its sync (made pages only)
        self.page_recolors: dict = {}           # key -> its recolor
        self.heroes: dict = {}                  # key -> (icon, title, words)
        self.on_card: list = []                 # page widgets on a card: the card's colour
        self.card_labels: list = []             # ... text in the note's ink
        self.card_muted: list = []              # ... quieter text
        self._builders = {"set_color": lambda p: self._b_color(p, "memo"),
                          "set_default_color": lambda p: self._b_color(p, "default"),
                          "set_theme_color": lambda p: self._b_color(p, "theme"),
                          "set_transparency": self._b_alpha, "set_font": self._b_font,
                          "set_date_format": self._b_date, "set_snap": self._b_snap,
                          "set_minimize": self._b_minimize, "set_folder": self._b_folder,
                          "set_keys": self._b_keys, "set_update": self._b_update}

    def has_page(self, key) -> bool:
        return key in self._builders

    def _make_page(self, key):
        build = self._builders.get(key)
        if build is None:
            return None
        p = self._page_frame(key)
        dict.__setitem__(self.pages, key, p)
        build(p)
        try:
            self.recolor(self.nw.colors)        # (its widgets take the note's colours, and sync)
        except tk.TclError:
            pass
        return p

    def _wrap(self, label, least=120):
        px = self.app.px
        label.bind("<Configure>", lambda e, w=label: w.configure(wraplength=max(px(least), e.width)))
        return label

    def _page_frame(self, key):
        from ui_views import SETTING_HELP
        px = self.app.px
        p = tk.Frame(self.detail_area.inner, bd=0)
        self.rows.append(p)
        hero = tk.Frame(p, bd=0)
        hero.pack(fill="x", padx=px(14), pady=(px(12), px(12)))
        self.rows.append(hero)
        icon = tk.Label(hero, bd=0)
        icon.pack(side="left", anchor="n", padx=(0, px(10)))
        words = tk.Frame(hero, bd=0)
        words.pack(side="left", fill="x", expand=True)
        self.rows.append(words)
        title = self._wrap(tk.Label(words, text=tr(key), font=ui_font(11, True), anchor="w", justify="left"))
        title.pack(fill="x")
        self.labels.append(title)
        sub = self._wrap(tk.Label(words, text=tr(PAGE_SUBTITLES.get(key, SETTING_HELP[key])), font=(UI_FONT, 9),
                                  anchor="w", justify="left"))
        sub.pack(fill="x", pady=(px(2), 0))
        self.muted.append(sub)
        self.heroes[key] = (icon, title, sub)
        return p

    def _card(self, p, caption=None):
        """A clear card on page ``p`` (under its ``caption``); returns its inside."""
        px = self.app.px
        if caption:
            cap = tk.Label(p, text=caption, font=(UI_FONT, 8), anchor="w")
            cap.pack(fill="x", padx=px(16), pady=(0, px(4)))
            self.muted.append(cap)
        card = tk.Frame(p, bd=0)
        card.pack(fill="x", padx=px(14))
        strips = []
        for _ in range(3):
            strip = tk.Frame(p, height=1, bd=0)
            strip.pack(fill="x", padx=px(14))
            strips.append(strip)
        self.cards.append((card, strips))
        gap = tk.Frame(p, height=px(10), bd=0)
        gap.pack(fill="x")
        self.rows.append(gap)
        inner = tk.Frame(card, bd=0)
        inner.pack(fill="x", padx=px(10), pady=px(8))
        self.on_card.append(inner)
        return inner

    def _on_card(self, *widgets):
        self.on_card.extend(widgets)
        return widgets[0] if len(widgets) == 1 else widgets

    def _card_text(self, master, text="", muted=False, font=None, wrap=False, **kw):
        lbl = tk.Label(master, text=text, font=font or (UI_FONT, 9), anchor="w", justify="left", **kw)
        (self.card_muted if muted else self.card_labels).append(lbl)
        return self._wrap(lbl, 60) if wrap else lbl

    def _recolor_pages(self, c, k):
        """The made pages' shared parts (SettingsView.recolor runs this): icons, cards, their text."""
        px = self.app.px
        ink = readable(self.frame, c.muted, k.rest, MARK_CONTRAST)
        for key, (icon, _title, _words) in self.heroes.items():
            from ui_views import SETTING_ICONS
            icon._photo = hero_photo(self.app, SETTING_ICONS[key], ink, k.rest, k.edge, px(HERO_PX))
            icon.configure(image=icon._photo or "", bg=c.bg)
        for w in self.on_card:
            w.configure(bg=k.rest)
        for w in self.card_labels:
            w.configure(bg=k.rest, fg=c.fg)
        for w in self.card_muted:
            w.configure(bg=k.rest, fg=readable(self.frame, c.muted, k.rest, TEXT_CONTRAST))
        for fn in self.page_recolors.values():
            fn(c, k)

    def _sync_pages(self):
        for fn in self.page_syncs.values():
            fn()

    def _chip(self, c, k):
        """The chosen row's colours on a card: (fill, edge) — raised, like the chosen choice."""
        return self._choice_colors(c, k.rest)[1:]

    def _choice_rows(self, inner, items, choose):
        """Rows to choose one of (date format, minimize): each ``(value, parts builder)``; the chosen
        one raised with a ✓. Returns value -> (row, [its widgets], check)."""
        px = self.app.px
        rows = {}
        for value, build in items:
            row = tk.Frame(inner, bd=0, cursor="hand2", highlightthickness=px(1))
            row.pack(fill="x", pady=(0, px(2)))
            check = tk.Label(row, bd=0, cursor="hand2")
            check.pack(side="right", padx=(px(6), px(8)))
            parts = build(row)
            widgets = [row, check] + list(parts)
            for w in widgets:
                w.bind("<ButtonRelease-1>", lambda e, v=value: choose(v))
            rows[value] = (row, widgets, check)
        return rows

    def _paint_rows(self, rows, now):
        c, k = self.nw.colors, self._card_colors()
        fill, edge = self._chip(c, k)
        tick = readable(self.frame, accent_color(self.frame, self.app.theme_colors().color, fill), fill, MARK_CONTRAST)
        for value, (row, widgets, check) in rows.items():
            on = value == now
            bg = fill if on else k.rest
            for w in widgets:
                w.configure(bg=bg)
            row.configure(highlightbackground=edge if on else k.rest, highlightcolor=edge if on else k.rest)
            if on:
                paint_glyph(self.app, check, GLYPH["check"], tick, box=ICON_BOX)
            else:
                check.configure(image="", text="")

    # -- the colour pages: round swatches, my colours, a preview
    def _b_color(self, p, which):
        px = self.app.px
        inner = self._card(p)
        size = px(SWATCH_PX)
        gap = px(6)
        grid = self._on_card(tk.Frame(inner, bd=0))
        grid.pack(anchor="w")
        basic, custom = [], []
        for i, (name, color) in enumerate(PALETTE):
            cv = self._on_card(tk.Canvas(grid, width=size, height=size, highlightthickness=0, bd=0, cursor="hand2"))
            cv.grid(row=i // 5, column=i % 5, padx=(0, gap), pady=(0, gap))
            cv.bind("<ButtonRelease-1>", lambda e, c=color: self._pick(which, c))
            Tooltip(cv, tr(f"color_{name.lower()}"))
            basic.append((cv, color))
        self._card_text(inner, tr("my_colors"), muted=True, font=(UI_FONT, 8)).pack(anchor="w", pady=(px(4), px(4)))
        mine = self._on_card(tk.Frame(inner, bd=0))
        mine.pack(anchor="w")
        for i in range(CUSTOM_COLORS):
            cv = self._on_card(tk.Canvas(mine, width=size, height=size, highlightthickness=0, bd=0, cursor="hand2"))
            cv.grid(row=0, column=i, padx=(0, gap))
            cv.bind("<ButtonRelease-1>", lambda e, i=i: self.custom_click(which, i))
            cv.bind("<Button-3>", lambda e, i=i: self._custom_menu(e, which, i))
            Tooltip(cv, tr("tip_custom_color"))
            custom.append(cv)
        self.palettes[which] = (basic, custom)
        warn = self._on_card(tk.Frame(inner, bd=0))       # a colour too strong for text: what happens
        words = self._card_text(warn, muted=True, wrap=True)
        words.pack(fill="x")
        switch = FlatButton(warn, tr("keep_solid"), lambda: self._toggle_solid(which))
        switch.pack(anchor="w", pady=(px(3), px(2)))
        self.flat.append(switch)
        self.warnings[which] = (warn, words, switch, Tooltip(words, ""), mine, dict(padx=0))
        prev = self._card(p, tr("preview"))
        if which == "theme":                # the calendar's today and the text cursor in that colour
            row = self._on_card(tk.Frame(prev, bd=0))
            row.pack(fill="x")
            today = self._on_card(tk.Label(row, bd=0))
            today.pack(side="left")
            self._card_text(row, tr("today_label")).pack(side="left", padx=(px(6), px(14)))
            caret = self._on_card(tk.Frame(row, width=px(2), height=px(16), bd=0))
            caret.pack(side="left")
            self._card_text(row, tr("cursor_label")).pack(side="left", padx=(px(6), 0))
            parts = (today, caret)
        else:                               # a small note in that colour
            note = tk.Frame(prev, bd=0, highlightthickness=1)
            note.pack(fill="x")
            day = tk.Label(note, text=texts.date_row(date.today())[0] + "  " + texts.date_row(date.today())[1],
                           font=ui_font(9, True), anchor="w")
            day.pack(fill="x", padx=px(8), pady=(px(6), 0))
            line = tk.Label(note, text=tr("preview_memo"), font=(UI_FONT, 9), anchor="w")
            line.pack(fill="x", padx=px(8), pady=(px(2), px(8)))
            parts = (note, day, line)

        def sync():
            self._sync_palette(which)
            key = {"memo": "set_color", "default": "set_default_color", "theme": "set_theme_color"}[which]
            self.heroes[key][1].configure(text=f"{tr(key)} · {self._value_text(key)}")
            color = self._shown_color(which)
            if which == "theme":
                today, caret = parts
                k = self._card_colors()
                today._photo = dot_photo(self.app, color, readable(self.frame, Colors.of(today, color, solid=True).border,
                                                                   k.rest, MARK_CONTRAST), px(18), 1)
                today.configure(image=today._photo)
                caret.configure(bg=self.app.cursor_color(k.rest))
            else:
                note, day, line = parts
                pc = Colors.of(note, color)
                for w in (note, day, line):
                    w.configure(bg=pc.bg)
                day.configure(fg=pc.fg)
                line.configure(fg=pc.fg)
                note.configure(highlightbackground=pc.border, highlightcolor=pc.border)
        self.page_syncs[{"memo": "set_color", "default": "set_default_color", "theme": "set_theme_color"}[which]] = sync

    def _draw_swatch(self, cv, color, selected):
        """A round swatch on the card: the colour itself, ringed so it shows on its own colour; the
        one in use has a tick and a stronger ring."""
        c = Colors.of(cv, color, solid=True)
        card = self._card_colors().rest
        cv.delete("all")
        size = int(cv.cget("width"))
        ring = readable(cv, c.fg if selected else c.border, card, MARK_CONTRAST if selected else 1.4)
        cv._photo = dot_photo(self.app, color, ring, size, 2 if selected else 1, check=c.fg if selected else None)
        cv.create_image(size // 2, size // 2, image=cv._photo)

    def _draw_empty(self, cv, add):
        """An empty round slot; the next one to fill has a + in it."""
        c, card = self.nw.colors, self._card_colors().rest
        cv.delete("all")
        size = int(cv.cget("width"))
        cv._photo = dot_photo(self.app, card, c.muted if add else c.border, size, 1)
        cv.create_image(size // 2, size // 2, image=cv._photo)
        if add:
            m, arm = size // 2, max(3, size // 5)
            cv.create_line(m - arm, m, m + arm + 1, m, fill=c.muted)
            cv.create_line(m, m - arm, m, m + arm + 1, fill=c.muted)
        cv.configure(cursor="hand2" if add else "")

    # -- transparency: the slider and its number, marks, a note fading over a desktop
    def _b_alpha(self, p):
        px = self.app.px
        inner = self._card(p)
        row = self._on_card(tk.Frame(inner, bd=0))
        row.pack(fill="x")
        col = self._on_card(tk.Frame(row, bd=0))      # (packed after the number: it takes what is left)
        self.alpha = Slider(col, self.app, 0, 90, self._alpha_moved)
        self.alpha.pack(fill="x")
        marks = self._on_card(tk.Frame(col, bd=0, height=px(14)))
        marks.pack(fill="x")
        for v in (0, 25, 50, 75, 90):       # (the ends kept inside: the first from its left, the last its right)
            m = self._card_text(marks, str(v), muted=True, font=(UI_FONT, 8))
            m.place(relx=0.03 + 0.94 * v / 90, rely=0, anchor={0: "nw", 90: "ne"}.get(v, "n"))
        self.alpha_unit = self._card_text(row, "%", muted=True)
        self.alpha_unit.pack(side="right", anchor="n", pady=px(3))
        self.alpha_box = NumberBox(row, self.app, 0, 90, self._alpha_typed)
        self.alpha_box.pack(side="right", anchor="n", padx=(px(8), px(2)))
        col.pack(side="left", fill="x", expand=True)
        _finish_typing_first(self.alpha_box.entry)
        self.alpha_box.entry.bind("<FocusIn>", lambda e: winapi.hide_ime_box(self.nw.win.winfo_id()), add="+")
        prev = self._card(p, tr("preview"))
        shown = self._on_card(tk.Label(prev, bd=0))
        shown.pack(anchor="w")

        def sync():
            t = self.nw.pad.transparency
            self.alpha.set(t)
            self.alpha_box.set(t)
            shown._photo = self._alpha_preview(t)
            shown.configure(image=shown._photo)

        def recolor(c, k):
            self.alpha.recolor(c)
            self.alpha.configure(bg=k.rest)
            self.alpha_box.recolor(c)
        self.page_syncs["set_transparency"] = sync
        self.page_recolors["set_transparency"] = recolor

    def _alpha_preview(self, t):
        """A desktop of stripes with a note in this note's colour over it, ``t`` % see-through."""
        px, c = self.app.px, self.nw.colors
        key = ("alpha_preview", t, c.bg, c.fg, px(1))
        photo = self.app.icons._photos.get(key)
        if photo is not None:
            return photo
        w, h = px(220), px(96)
        img = Image.new("RGB", (w, h), (47, 77, 105))
        d = ImageDraw.Draw(img)
        for x in range(-h, w, px(12)):
            d.polygon([(x, h), (x + px(6), h), (x + px(6) + h, 0), (x + h, 0)], fill=(59, 91, 122))
        for i, y in enumerate((px(12), px(26), px(40))):            # the words of a window behind it
            d.rectangle((px(10), y, px(10) + px(70 - 14 * i), y + px(5)), fill=(200, 214, 226))
        note = Image.new("RGB", (px(132), px(62)), ImageColor.getrgb(c.bg))
        nd = ImageDraw.Draw(note)
        nd.rectangle((px(8), px(8), px(40), px(16)), fill=ImageColor.getrgb(c.fg))
        nd.rectangle((px(8), px(26), px(96), px(31)), fill=ImageColor.getrgb(c.muted))
        nd.rectangle((px(8), px(38), px(76), px(43)), fill=ImageColor.getrgb(c.muted))
        box = (px(60), px(18))
        under = img.crop((box[0], box[1], box[0] + note.width, box[1] + note.height))
        img.paste(Image.blend(note, under, t / 100), box)
        photo = self.app.icons._photos[key] = ImageTk.PhotoImage(img, master=self.app.icons.root)
        return photo

    # -- font: the picker, − size +, a sample in the font
    def _b_font(self, p):
        px = self.app.px
        inner = self._card(p)
        self.font_picker = FontPicker(inner, self.app, lambda fam: self.nw.set_font(family=fam))
        self.font_picker.pack(fill="x")
        row = self._on_card(tk.Frame(inner, bd=0))
        row.pack(fill="x", pady=(px(8), 0))
        self._card_text(row, tr("font_size")).pack(side="left")
        self.size_box = Stepper(row, self.app, 8, 48, lambda v: self.nw.set_font(size=v))
        self.size_box.pack(side="right")
        prev = self._card(p, tr("preview"))
        sample = self._card_text(prev, tr("font_preview"), wrap=True)
        sample.pack(fill="x")

        def sync():
            n = self.nw.note
            self.font_picker.set(n.font_family)
            self.size_box.set(n.font_size)
            sample.configure(font=(n.font_family, n.font_size))

        def recolor(c, k):
            self.font_picker.recolor(c)
            self.size_box.recolor(k.rest, c.fg, k.muted, k.edge, k.lit)
        self.page_syncs["set_font"] = sync
        self.page_recolors["set_font"] = recolor

    # -- date format: a row per format with today in it, and a list card's date
    def _b_date(self, p):
        px = self.app.px
        inner = self._card(p)
        today = date.today()

        def maker(fmt):
            def build(row):
                text = tk.Label(row, text=texts.day_label(today, fmt), font=(UI_FONT, 9), anchor="w", cursor="hand2")
                text.pack(side="left", fill="x", expand=True, padx=(px(8), 0), pady=px(5))
                self.card_labels.append(text)
                return (text,)
            return build
        self.date_rows = self._choice_rows(inner, [(fmt, maker(fmt)) for fmt in texts.DATE_FORMATS],
                                           self.app.set_date_format)
        prev = self._card(p, tr("preview"))
        card = self._on_card(tk.Frame(prev, bd=0))
        card.pack(fill="x")
        bar = tk.Frame(card, width=px(3), bd=0)
        bar.pack(side="left", fill="y")
        body = self._on_card(tk.Frame(card, bd=0))
        body.pack(side="left", fill="x", expand=True, padx=(px(8), 0))
        title = self._card_text(body, font=ui_font(9, True))
        title.pack(fill="x")
        when = self._card_text(body, muted=True)
        when.pack(fill="x")

        def sync():
            self._paint_rows(self.date_rows, texts.date_format())
            title.configure(text=self.nw.win.title() or tr("untitled"))
            when.configure(text=f"{tr('current')} · {texts.day_label(date.today(), texts.date_format())}")

        def recolor(c, k):
            bar.configure(bg=accent_color(self.frame, self.app.theme_colors().color, k.rest))
        self.page_syncs["set_date_format"] = sync
        self.page_recolors["set_date_format"] = recolor

    # -- snap: the gap chips, two notes drawn that far apart
    def _b_snap(self, p):
        px = self.app.px
        inner = self._card(p)
        row = self._on_card(tk.Frame(inner, bd=0))
        row.pack(fill="x")
        seg = tk.Frame(row, bd=0, padx=px(2), pady=px(2))
        seg.pack(side="left")
        self.segs.append(seg)
        self.snap_buttons = {}
        for gap in (None, *SNAP_GAPS):
            b = FlatButton(seg, tr("snap_off") if gap is None else f"{gap}", lambda g=gap: self.app.set_snap_gap(g))
            b.configure(padx=px(7), pady=px(1))
            b.pack(side="left")
            self.snap_buttons[gap] = b
            self.flat.append(b)
        self.snap_unit = self._card_text(row, "px", muted=True)
        self.snap_unit.pack(side="left", padx=(px(6), 0))
        prev = self._card(p, tr("preview"))
        cv = self._on_card(tk.Canvas(prev, width=px(220), height=px(84), bd=0, highlightthickness=0))
        cv.pack(anchor="w")

        def sync():
            c, k = self.nw.colors, self._card_colors()
            gap = self.app.prefs.snap_gap
            cv.delete("all")
            w, h = px(220), px(84)
            cv.create_rectangle(0, 0, w, h, fill=_mix(self.frame, k.rest, c.fg, 0.10), width=0)
            x0, y0, nw_, nh = px(18), px(14), px(78), px(56)
            cv.create_rectangle(x0, y0, x0 + nw_, y0 + nh, fill=c.bg, outline=c.border)
            far = gap is None
            g = px(34) if far else round(px(gap) * 1.6)
            x1 = x0 + nw_ + g
            other = Colors.of(cv, "#CFE6FF" if str(c.bg).upper() != "#CFE6FF" else "#FFE0B8")
            cv.create_rectangle(x1, y0, x1 + nw_, y0 + nh, fill=other.bg, outline=other.border)
            ink = readable(self.frame, c.muted, k.rest, MARK_CONTRAST)
            if not far and g:
                for x in (x0 + nw_, x1):
                    cv.create_line(x, px(6), x, h - px(16), fill=ink, dash=(2, 2))
            label = tr("snap_off") if far else f"{gap}px"
            cv.create_text(x0 + nw_ + g / 2, h - px(8), text=label, fill=ink, font=(UI_FONT, 8))
            self._paint_choices(self.snap_buttons, gap, self._well(c, k))
        self.page_syncs["set_snap"] = sync

    # -- minimize: three options, each drawn, a line each
    def _b_minimize(self, p):
        px = self.app.px
        inner = self._card(p)

        def maker(style):
            def build(row):
                pic = tk.Label(row, bd=0, cursor="hand2")
                pic.pack(side="left", padx=(px(6), px(10)), pady=px(6))
                words = tk.Frame(row, bd=0, cursor="hand2")
                words.pack(side="left", fill="x", expand=True, pady=px(6))
                name = tk.Label(words, text=tr(f"min_{style}"), font=ui_font(9, True), anchor="w", cursor="hand2")
                name.pack(fill="x")
                self.card_labels.append(name)
                desc = self._wrap(tk.Label(words, text=tr(f"min_{style}_desc"), font=(UI_FONT, 8), anchor="w",
                                           justify="left", cursor="hand2"), 60)
                desc.pack(fill="x")
                self.card_muted.append(desc)
                self._min_pics[style] = pic
                return (pic, words, name, desc)
            return build
        self._min_pics = {}
        self.min_rows = self._choice_rows(inner, [(s, maker(s)) for s in MIN_STYLES], self.app.set_minimize_style)

        def sync():
            self._paint_rows(self.min_rows, self.app.prefs.minimize_style)
            for style, pic in self._min_pics.items():
                pic._photo = self._min_photo(style)
                pic.configure(image=pic._photo)
        self.page_syncs["set_minimize"] = sync

    def _min_photo(self, style):
        """What − does, drawn small (smooth): the desk, and the note as it is left on it."""
        px, c = self.app.px, self.nw.colors
        desk = _mix(self.frame, self._card_colors().rest, c.fg, 0.12)
        key = ("min_pic", style, desk, c.bg, c.border, px(1))
        photo = self.app.icons._photos.get(key)
        if photo is not None:
            return photo
        w, h, s = px(58), px(38), 8
        big = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=px(4) * s, fill=ImageColor.getrgb(desk))
        note, edge = ImageColor.getrgb(c.bg), ImageColor.getrgb(c.border)
        if style == "bar":                  # the top bar left where the note was
            d.rounded_rectangle((px(6) * s, px(6) * s, (w - px(6)) * s, px(14) * s), radius=px(2) * s,
                                fill=note, outline=edge, width=s)
        elif style == "fold":               # gone to the taskbar: a small button on its bar
            d.rectangle((0, (h - px(8)) * s, w * s, h * s), fill=ImageColor.getrgb(_mix(self.frame, desk, c.fg, 0.25)))
            d.rounded_rectangle((px(22) * s, (h - px(7)) * s, px(36) * s, (h - px(1)) * s), radius=px(1) * s,
                                fill=note, outline=edge, width=s)
        else:                               # a round sticker on the desk
            r = px(8) * s
            cx, cy = w * s // 2, h * s // 2
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=note, outline=edge, width=s * 2)
        photo = self.app.icons._photos[key] = ImageTk.PhotoImage(big.reduce(s), master=self.app.icons.root)
        return photo

    # -- memo folder: its name, the path cut in the middle, open and copy, what is in it
    def _b_folder(self, p):
        px = self.app.px
        folder = Path(self.app.store.folder)
        inner = self._card(p)
        self._card_text(inner, folder.name, font=ui_font(10, True)).pack(fill="x")
        self.folder_path = self._card_text(inner, str(folder), muted=True)
        self.folder_path.pack(fill="x")
        Tooltip(self.folder_path, str(folder))
        f = tkfont.Font(font=(UI_FONT, 9))
        self.folder_path.bind("<Configure>", lambda e: self.folder_path.configure(
            text=_middle_cut(str(folder), max(px(60), e.width - px(4)), f.measure)))
        row = self._on_card(tk.Frame(inner, bd=0))
        row.pack(fill="x", pady=(px(8), 0))
        open_b = FlatButton(row, tr("open_folder"), self.app.open_folder)
        open_b.pack(side="left")
        copy_b = FlatButton(row, tr("copy_path"), lambda: self._copy_path(copy_b, folder))
        copy_b.pack(side="left", padx=(px(6), 0))
        self.flat += [open_b, copy_b]
        stats = self._card(p)
        cols = []
        for caption in ("stat_memos", "stat_pictures", "stat_backups"):
            col = self._on_card(tk.Frame(stats, bd=0))
            col.pack(side="left", fill="x", expand=True)
            num = self._card_text(col, font=ui_font(13, True))
            num.pack(anchor="w")
            self._card_text(col, tr(caption), muted=True, font=(UI_FONT, 8)).pack(anchor="w")
            cols.append(num)

        def sync():
            memos = sum(1 for n in self.app.notes.values() if not n.deleted and not n.is_empty)
            try:
                pictures = sum(1 for _ in self.app.store.images.iterdir()) if self.app.store.images.exists() else 0
                backups = folder / "backups"
                kept = min(BACKUPS_KEPT, sum(1 for _ in backups.glob("*.json"))) if backups.exists() else 0
            except OSError:
                pictures, kept = 0, 0
            days = tr("days_1") if kept == 1 else tr("days_n", n=kept)
            for num, value in zip(cols, (str(memos), str(pictures), days)):
                num.configure(text=value)
        self.page_syncs["set_folder"] = sync

    def _copy_path(self, button, folder):
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(str(folder))
        except tk.TclError:
            return
        button.configure(text=tr("copied"))
        self.frame.after(1600, lambda: button.winfo_exists() and button.configure(text=tr("copy_path")))

    # -- keys: cards by what they are for, each key a keycap
    def _b_keys(self, p):
        from ui_views import GESTURE_ROWS, KEY_ROWS
        px = self.app.px
        words_of = dict(KEY_ROWS)
        self.key_rows = {}
        self._keycaps = []
        for head, combos in KEY_GROUPS:
            inner = self._card(p, tr(head))
            for combo in combos:
                row = self._on_card(tk.Frame(inner, bd=0))
                row.pack(fill="x", pady=px(3))
                caps = self._on_card(tk.Frame(row, bd=0))
                caps.pack(side="right")
                labels = []
                for part in _key_parts(combo):
                    cap = tk.Label(caps, text=part, bd=0)
                    cap.pack(side="left", padx=(px(2), 0))
                    self._keycaps.append(cap)
                    labels.append(cap)
                self._card_text(row, tr(words_of[combo]), wrap=True).pack(side="left", fill="x", expand=True)
                self.key_rows[combo] = labels
        inner = self._card(p, tr("keys_mouse"))
        for first, words in GESTURE_ROWS:
            row = self._on_card(tk.Frame(inner, bd=0))
            row.pack(fill="x", pady=px(3))
            self._card_text(row, tr(words), wrap=True).pack(fill="x")
            self._card_text(row, tr(first), muted=True, font=(UI_FONT, 8), wrap=True).pack(fill="x")

        def recolor(c, k):
            dark = luminance(self.frame, k.rest) < 0.18
            fill = _mix(self.frame, k.rest, "#FFFFFF", 0.12 if dark else 0.75)
            edge = _mix(self.frame, k.rest, c.fg, 0.28)
            for cap in self._keycaps:
                cap._photo = keycap_photo(self.app, cap.cget("text"), c.fg, fill, edge, px(KEYCAP_PX))
                cap.configure(image=cap._photo, bg=k.rest)
        self.page_recolors["set_keys"] = recolor

    # -- update: the version large, its state with an icon, when it was checked, the notes
    def _b_update(self, p):
        px = self.app.px
        inner = self._card(p)
        top = self._on_card(tk.Frame(inner, bd=0))
        top.pack(fill="x")
        self._card_text(top, f"v{version.VERSION}", font=ui_font(16, True)).pack(side="left")
        self._card_text(top, tr("upd_installed", v=version.VERSION), muted=True).pack(side="left", padx=(px(8), 0),
                                                                                     anchor="s", pady=(0, px(3)))
        state = self._on_card(tk.Frame(inner, bd=0))
        state.pack(fill="x", pady=(px(6), 0))
        self._update_icon = self._on_card(tk.Label(state, bd=0))
        self._update_icon.pack(side="left", padx=(0, px(4)))
        self.update_status = self._card_text(state, font=ui_font(9, True), wrap=True)
        self.update_status.pack(side="left", fill="x", expand=True)
        self._update_when = self._card_text(inner, muted=True, font=(UI_FONT, 8))
        self._update_when.pack(fill="x")
        row = self._on_card(tk.Frame(inner, bd=0))
        row.pack(fill="x", pady=(px(8), 0))
        self.update_check = FlatButton(row, tr("upd_check"), self.app.update_check)
        self.update_check.pack(side="left")
        self.flat.append(self.update_check)
        self.update_box = tk.Frame(p, bd=0)              # the offer: the notes, Update now / Not now
        self.update_box.pack(fill="x", padx=px(14))
        self.rows.append(self.update_box)
        self.update_notes = self._wrap(tk.Label(self.update_box, font=(UI_FONT, 9), anchor="w", justify="left"))
        self.muted.append(self.update_notes)
        self.update_buttons = tk.Frame(self.update_box, bd=0)
        self.rows.append(self.update_buttons)
        self.update_now = FlatButton(self.update_buttons, tr("upd_now"), self.app.update_install)
        self.update_now.pack(side="left", padx=(0, px(6)))
        self.update_later = FlatButton(self.update_buttons, tr("upd_later"), lambda: self.app.updater.dismiss())
        self.update_later.pack(side="left")
        self.flat += [self.update_now, self.update_later]
        self.update_elsewhere = self._wrap(tk.Label(self.update_box, font=(UI_FONT, 9), anchor="w", justify="left"))
        self.update_elsewhere.configure(text=tr("upd_elsewhere"))
        self.muted.append(self.update_elsewhere)
        self._updater = self.app.updater
        self._updater.listeners.append(self._sync_update)
        self.page_syncs["set_update"] = self._sync_update

    def _sync_update(self):
        if "set_update" not in self.pages:
            return
        u, px = self.app.updater, self.app.px
        c, k = self.nw.colors, self._card_colors()
        if getattr(self, "_update_seen", None) == "checking" and u.state in ("latest", "available", "error"):
            u.checked_at = datetime.now()           # (every note's page shows the same time)
        self._update_seen = u.state
        for w in self.update_box.winfo_children():
            w.pack_forget()
        release = u.release
        status = {"checking": lambda: tr("upd_checking"), "latest": lambda: tr("upd_latest"),
                  "error": lambda: tr(u.error, e=u.error_detail) if u.error else "",
                  "available": lambda: tr("upd_new", v=release.version) if release else "",
                  "downloading": lambda: tr("upd_downloading", pct=round(u.progress * 100)),
                  "installing": lambda: tr("upd_installing")}.get(u.state, lambda: "")()
        self.update_status.configure(text=status or tr("upd_not_checked"))
        tone = {"latest": c.done if hasattr(c, "done") else c.fg, "error": c.danger}.get(u.state, c.fg)
        ink = readable(self.frame, tone, k.rest, TEXT_CONTRAST)
        self.update_status.configure(fg=ink)
        glyph = UPDATE_ICONS.get(u.state)
        if glyph:
            paint_glyph(self.app, self._update_icon, glyph, ink, box=ICON_BOX)
        else:
            self._update_icon.configure(image="")
        at = getattr(u, "checked_at", None)
        self._update_when.configure(text=tr("upd_checked", t=at.strftime("%H:%M")) if at else "")
        if u.state == "available" and release is not None:
            from ui_views import UPDATE_NOTE_LINES
            lines = release.notes.split("\n") if release.notes else []
            if len(lines) > UPDATE_NOTE_LINES:
                lines = lines[:UPDATE_NOTE_LINES] + ["…"]
            if lines:
                self.update_notes.configure(text="\n".join(lines))
                self.update_notes.pack(fill="x", pady=(px(2), 0))
            if u.can_install:
                self.update_buttons.pack(anchor="w", pady=(px(8), px(10)))
            else:                               # (a run from the repo or an unzipped folder)
                self.update_elsewhere.pack(fill="x", pady=(px(8), px(10)))
        busy = u.state in ("checking", "downloading", "installing")     # Check does nothing then
        self.update_check.configure(fg=c.muted if busy else c.fg, cursor="" if busy else "hand2")
