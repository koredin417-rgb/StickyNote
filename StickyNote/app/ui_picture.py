"""Pictures of an image-style memo: viewer, zoom, thumbnail tabs."""
from __future__ import annotations

import calendar as _calendar
import colorsys
from collections import OrderedDict
import os
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageTk

import holidays
import texts
import winapi
from icon import draw_icon
from store import (BIN_DAY_CHOICES, CURSOR_COLORS, CUSTOM_COLORS, EMPTY_TITLE, INLINE, LIST_SORTS, MARK_KINDS,
                   PIN_LIMIT_MAX, SNAP_GAPS, STYLES, TIDY_ORDERS, Note, NoteStore, Pad, Prefs)
from texts import tr
from ui_calendar import *  # noqa: F401,F403  (the parts before this one)


# --------------------------------------------------------------------------- image viewer
class ImageViewer:
    """The pictures of an image-style memo: the chosen one large, and under it a
    strip of thumbnails ending in a + tile. Over the large picture the mouse wheel
    zooms around the pointer, dragging pans, and a double-click shows it whole again."""

    ZOOM_STEP = 1.25
    ZOOM_MAX = 8.0

    def __init__(self, nw: NoteWindow):
        self.nw, self.app = nw, nw.app
        px = self.app.px
        self.index = 0                  # which of the memo's pictures is shown
        self.zoom = 1.0                 # 1 = the whole picture fits
        self.offset = (0, 0)            # top-left corner of the view, in picture pixels
        self.tiles: list = []           # (x0, x1, picture index or "add") along the strip
        self.shown_name: str | None = None
        self._source = None             # (name, PIL image or None if unreadable)
        self._fit = 1.0                 # screen pixels per picture pixel at zoom 1
        self._view = (1, 1)             # size of the picture on screen
        self._photo = None
        self._thumbs: dict = {}
        self._pan = None
        self._scroll = 0                # strip scrolled left by this many pixels
        self._strip_end = 0
        self.thumb_h = px(34)
        self._base = None               # the picture as drawn (full width), before the < > arrows
        self._shown = None              # ... and with them, as on screen
        self._full_w = 1                # the picture area is always the note's full width ...
        self._pic_x = 0                 # ... and the picture sits in its middle, this far from the left
        self._hover = None              # "prev" / "next" while the mouse is over that arrow
        self._press_arrow = None

        self.frame = tk.Frame(nw.home, bd=0)
        c = self.canvas = tk.Canvas(self.frame, bd=0, highlightthickness=0)
        c.pack()
        self.strip = tk.Canvas(self.frame, height=self.thumb_h + px(6), bd=0, highlightthickness=0,
                               cursor="hand2")
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._move)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", lambda e: self.fit())
        c.bind("<Motion>", lambda e: self._set_hover(self.arrow_at(e.x)))
        c.bind("<Leave>", lambda e: self._set_hover(None))
        c.bind("<Button-3>", lambda e: nw._image_menu(e, self.index if nw.note.images else None))
        self.strip.bind("<ButtonRelease-1>", self._strip_click)
        self.strip.bind("<Button-3>", self._strip_menu)
        self.strip.bind("<MouseWheel>", self._strip_wheel)
        Tooltip(self.strip, tr("tip_strip"))

    # -- state
    @property
    def has_picture(self):
        return self._source is not None and self._source[1] is not None

    def release(self):
        """The window is closing: drop the pictures (the full-size source above all)."""
        self._photo = self._source = self._base = self._shown = None
        self._thumbs.clear()

    def reset(self):
        """Forget the shown picture (another memo is being loaded)."""
        stop_animation(self.canvas, "fade")
        self.canvas.delete("all")       # items first: Tk 9 dislikes images freed under them
        self.strip.delete("all")
        self._photo = self._source = self.shown_name = self._base = self._shown = None
        self.index, self.zoom, self.offset, self._scroll = 0, 1.0, (0, 0), 0

    def forget(self, name):
        """A picture was removed from the memo: drop what was cached for it."""
        self.strip.delete("all")
        self._thumbs.pop(name, None)
        if self._source and self._source[0] == name:
            stop_animation(self.canvas, "fade")
            self.canvas.delete("all")
            self._photo = self._source = self.shown_name = self._base = self._shown = None

    def select(self, index):
        """Show picture ``index`` and its own text (a tab)."""
        self.nw.switch_tab(index)

    def step(self, delta):
        self.nw.switch_tab(self.index + delta)

    # -- drawing
    def _area(self):
        """Room for the picture: the note's full width, and at most 45 % of its height, less
        on a small note so the text keeps TEXT_MIN_LINES lines (the picture gives way)."""
        nw, px = self.nw, self.app.px
        width = nw.win.winfo_width() if nw.win.winfo_width() > 1 else nw.pad.width
        height = nw.win.winfo_height() if nw.win.winfo_height() > 1 else nw.pad.height
        others = (nw.grab.winfo_reqheight() + nw.bar.winfo_reqheight() + nw.format_bar.winfo_reqheight()
                  + self.strip.winfo_reqheight() + px(14))
        if nw.add_bar.winfo_manager():
            others += nw.add_bar.winfo_reqheight() + px(8)
        line = int(nw.body.tk.call("font", "metrics", nw.body.cget("font"), "-linespace"))
        text = line * TEXT_MIN_LINES + 2 * int(nw.body.cget("pady"))
        return max(40, width - px(18)), max(px(36), min(int(height * 0.45), height - others - text))

    def render(self, follow=False):
        """Redraw for the memo's pictures and the window's current size."""
        names = self.nw.note.images
        if not names:
            self.reset()
            self.strip.pack_forget()
            self._hint(tr("hint_add_pictures"), clickable=True, icon=GLYPH["picture"], key="Ctrl+V")
            return
        self.index = max(0, min(self.index, len(names) - 1))
        name = names[self.index]
        last = None
        if self._source is None or self._source[0] != name:
            last = self._shown                  # another picture of the same memo: fade over it
            try:
                pil = _open_image(self.app.store.image_path(name))
            except Exception:
                pil = None
            self._source, self.shown_name = (name, pil), name
            self.zoom, self.offset = 1.0, (0, 0)
        self.strip.pack(fill="x", pady=(self.app.px(4), 0))
        self._draw_strip(follow)
        if not self.has_picture:
            self._hint(tr("hint_missing_picture"))
            return
        max_w, max_h = self._area()
        iw, ih = self._source[1].size
        self._fit = min(max_w / iw, max_h / ih, 1.0)
        self._view = (max(1, round(iw * self._fit)), max(1, round(ih * self._fit)))
        self._full_w, self._pic_x = max_w, (max_w - self._view[0]) // 2
        self.canvas.configure(width=max_w, height=self._view[1])
        self._clamp()
        self._draw_picture(fade_from=last)

    def _hint(self, text, clickable=False, icon=None, key=None):
        """A line in place of the picture. With ``icon``: that icon and the ``key`` chip
        instead of the words (they stay in ``hint_text``)."""
        c, px = self.nw.colors, self.app.px
        stop_animation(self.canvas, "fade")
        self.canvas.delete("all")
        self._photo = self._base = self._shown = None
        self.hint_text = text
        w, h = self._area()[0], px(56)
        self.canvas.configure(width=w, height=h, cursor="hand2" if clickable else "")
        if not icon or not self.app.icons.available:
            self.canvas.create_text(w / 2, h / 2, text=text, fill=c.muted, tags="hint", font=(UI_FONT, 9))
            return
        font = tkfont.Font(self.canvas, family=UI_FONT, size=8)
        box, gap = px(20), px(10)
        kw, kh = font.measure(key) + px(10), px(18)
        x = (w - box - gap - kw) / 2
        self._hint_photo = self.app.icons.photo(icon, c.muted, box)
        self.canvas.create_image(x, h / 2, anchor="w", image=self._hint_photo, tags="hint")
        kx = x + box + gap
        self.canvas.create_polygon(_round_rect(kx, h / 2 - kh / 2, kx + kw, h / 2 + kh / 2, px(4)), smooth=True,
                                   fill=c.bg, outline=c.border, tags="hint")
        self.canvas.create_text(kx + kw / 2, h / 2, text=key, fill=c.muted, font=font, tags="hint")

    def _draw_picture(self, fade_from=None):
        pil = self._source[1]
        vw, vh = self._view
        if self.zoom == 1:
            img = pil.resize((vw, vh), Image.LANCZOS)
        else:
            s = self._fit * self.zoom
            ox, oy = self.offset
            box = (ox, oy, min(pil.width, ox + vw / s), min(pil.height, oy + vh / s))
            img = pil.resize((vw, vh), Image.NEAREST if s >= 2 else Image.BILINEAR, box=box)
        base = Image.new("RGBA", (self._full_w, vh), self.nw.colors.well)
        base.paste(img.convert("RGBA"), (self._pic_x, 0))
        self._base = base
        self._show(fade_from)

    def _show(self, fade_from=None):
        """Draw the picture with its < > arrows. ``fade_from``: the picture shown before,
        which fades into this one (PICTURE_FADE_MS)."""
        stop_animation(self.canvas, "fade")
        img = self._base
        for side in self.arrows():
            img = self._chevron(img, side, hover=side == self._hover)
        img = img.convert("RGB")
        self._shown = img
        self.canvas.delete("all")
        self._photo = ImageTk.PhotoImage(img, master=self.canvas)
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo, tags="picture")
        self.canvas.configure(cursor="hand2" if self._hover else ("fleur" if self.zoom > 1 else ""))
        if fade_from is not None:
            last = Image.new("RGB", img.size, self.nw.colors.well)     # the last picture, as big as this
            last.paste(fade_from.crop((0, 0, min(fade_from.width, img.width),
                                       min(fade_from.height, img.height))), (0, 0))
            photo = self._photo
            animate(self.canvas, "fade", PICTURE_FADE_MS, lambda k: photo.paste(Image.blend(last, img, k)))

    # -- < > arrows between the pictures (tabs)
    def arrows(self) -> list[str]:
        """Which arrows show: none for one picture, no < on the first, no > on the last."""
        n = len(self.nw.note.images)
        if n < 2 or not self.has_picture:
            return []
        return [side for side, ok in (("prev", self.index > 0), ("next", self.index < n - 1)) if ok]

    def arrow_at(self, x):
        zone = self.app.px(40)
        side = "prev" if x < zone else "next" if x > self._full_w - zone else None
        return side if side in self.arrows() else None

    def _set_hover(self, side):
        if side != self._hover:
            self._hover = side
            if self._base is not None:
                self._show()

    def _chevron(self, img, side, hover=False):
        """A plain < or > in the memo's text color, with a soft edge in the memo color so
        it shows on any picture. Faint until the mouse is over it."""
        c, px, s = self.nw.colors, self.app.px, 4
        h = px(22)
        w, stroke = max(4, round(h * 0.45)), max(2, px(3))
        pad = stroke * 2
        size = (w + 2 * pad, h + 2 * pad)
        mask = Image.new("L", (size[0] * s, size[1] * s), 0)
        tip, back = (pad, pad + w) if side == "prev" else (pad + w, pad)
        pts = [(back * s, pad * s), (tip * s, (pad + h / 2) * s), (back * s, (pad + h) * s)]
        d = ImageDraw.Draw(mask)
        d.line(pts, fill=255, width=stroke * s, joint="curve")
        for x, y in (pts[0], pts[2]):
            r = stroke * s / 2
            d.ellipse((x - r, y - r, x + r, y + r), fill=255)
        mask = mask.resize(size, Image.LANCZOS)
        halo = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1))
        a_fg, a_halo = (240, 190) if hover else (150, 110)
        fg = Image.new("RGBA", size, c.fg)
        fg.putalpha(mask.point(lambda v: v * a_fg // 255))
        edge = Image.new("RGBA", size, c.bg)
        edge.putalpha(halo.point(lambda v: v * a_halo // 255))
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        x = px(4) if side == "prev" else img.width - size[0] - px(4)
        y = (img.height - size[1]) // 2
        layer.alpha_composite(edge, (x, y))
        layer.alpha_composite(fg, (x, y))
        return Image.alpha_composite(img, layer)

    # -- zoom and pan
    def source_point(self, x, y):
        """The picture pixel under view position (x, y)."""
        s = self._fit * self.zoom
        return self.offset[0] + x / s, self.offset[1] + y / s

    def zoom_at(self, x, y, factor):
        if not self.has_picture:
            return
        zoom = min(self.ZOOM_MAX, max(1.0, self.zoom * factor))
        if zoom == self.zoom:
            return
        sx, sy = self.source_point(x, y)
        self.zoom = zoom
        s = self._fit * zoom
        self.offset = (sx - x / s, sy - y / s)    # keep that pixel under the pointer
        self._clamp()
        self._draw_picture()

    def fit(self):
        if self.has_picture and self.zoom != 1:
            self.zoom, self.offset = 1.0, (0, 0)
            self._draw_picture()

    def _clamp(self):
        if self.zoom == 1 or not self.has_picture:
            self.offset = (0, 0)
            return
        s = self._fit * self.zoom
        iw, ih = self._source[1].size
        vw, vh = self._view
        ox = min(max(self.offset[0], 0), max(0, iw - vw / s))
        oy = min(max(self.offset[1], 0), max(0, ih - vh / s))
        self.offset = (ox, oy)

    def _wheel(self, event):
        if event.delta:
            self.zoom_at(event.x - self._pic_x, event.y, self.ZOOM_STEP ** (event.delta / 120))
        return "break"

    def _press(self, event):
        self._press_arrow = self.arrow_at(event.x)
        self._pan = None if self._press_arrow else (event.x, event.y, *self.offset)

    def _move(self, event):
        if self._pan and self.zoom > 1:
            x0, y0, ox, oy = self._pan
            s = self._fit * self.zoom
            self.offset = (ox - (event.x - x0) / s, oy - (event.y - y0) / s)
            self._clamp()
            self._draw_picture()

    def _release(self, event):
        self._pan = None
        arrow, self._press_arrow = self._press_arrow, None
        if not self.nw.note.images:
            self.nw.pick_images()
        elif arrow and arrow == self.arrow_at(event.x):
            self.step(-1 if arrow == "prev" else 1)

    # -- thumbnail strip
    def _thumb(self, name):
        if name not in self._thumbs:            # kept here while the strip shows it
            self._thumbs[name] = self.app.picture(name, (round(self.thumb_h * 1.6), self.thumb_h))
        return self._thumbs[name]

    def _draw_strip(self, follow=False):
        st, c, px = self.strip, self.nw.colors, self.app.px
        th, gap, y0 = self.thumb_h, px(4), px(3)
        layout, x = [], px(8)
        for i, name in enumerate(self.nw.note.images):
            photo = self._thumb(name)
            w = photo.width() if photo else th
            layout.append((x, x + w, i, photo))
            x += w + gap
        layout.append((x, x + th, "add", None))         # + : one more picture, as a new tab
        self._strip_end = x + th + px(8)
        width = st.winfo_width() if st.winfo_width() > 1 else self._area()[0] + px(18)
        if follow:                                  # keep the shown picture's tile in view
            x0, x1 = layout[self.index][:2]
            if x1 - self._scroll > width - px(8):
                self._scroll = x1 - width + px(8)
            if x0 - self._scroll < px(8):
                self._scroll = x0 - px(8)
        self._scroll = max(0, min(self._scroll, self._strip_end - width))
        st.delete("all")
        self.tiles = []
        for x0, x1, what, photo in layout:
            x0, x1 = x0 - self._scroll, x1 - self._scroll
            self.tiles.append((x0, x1, what))
            if what == "add":
                st.create_rectangle(x0, y0, x1, y0 + th, outline=c.border, fill=c.well)
                m, arm = (x0 + x1) / 2, max(4, th // 5)
                st.create_line(m - arm, y0 + th / 2, m + arm + 1, y0 + th / 2, fill=c.muted, width=px(2))
                st.create_line(m, y0 + th / 2 - arm, m, y0 + th / 2 + arm + 1, fill=c.muted, width=px(2))
                continue
            st.create_rectangle(x0, y0, x1, y0 + th, outline="", fill=c.well)
            if photo is not None:
                st.create_image((x0 + x1) / 2, y0 + th / 2, image=photo)
            chosen = what == self.index         # the open tab: framed in a darker shade of the memo
            st.create_rectangle(x0, y0, x1, y0 + th, width=px(2) if chosen else 1,
                                outline=shade(st, self.nw.note.color, 3) if chosen else c.border)

    def _tile_at(self, x):
        return next((what for x0, x1, what in self.tiles if x0 <= x < x1), None)

    def _strip_click(self, event):
        what = self._tile_at(event.x)
        if what == "add":
            self.nw.pick_images()
        elif what is not None:
            self.select(what)

    def _strip_menu(self, event):
        what = self._tile_at(event.x)
        self.nw._image_menu(event, what if isinstance(what, int) else None)

    def _strip_wheel(self, event):
        width = self.strip.winfo_width()
        if self._strip_end > width:
            self._scroll -= int(event.delta / 120 * self.app.px(40))
            self._draw_strip()
        return "break"

    def recolor(self, c):
        self.frame.configure(bg=c.bg)
        self.canvas.configure(bg=c.well)
        self.strip.configure(bg=c.bg)
        if self.nw.note.style == "image":
            self.render()


# every name (underscored ones too) goes on to the next part: see app.py
__all__ = [_n for _n in list(globals()) if not _n.startswith("__")]
