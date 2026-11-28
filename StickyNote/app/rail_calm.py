"""Phase 11 (2026-11-28): the calm rail. A note's rail shows while the note has the keyboard focus or
the pointer, and goes RAIL_REST_MS after it has neither (a pass of the mouse does not flicker it).
Settings > 배치 > 레일 숨기기.

Resting, the rail gives its room to the memo (the user's call, after seeing an empty strip: a
resting note is one clean sheet). The swap happens under a picture of the note as it was, in a
click-through window over it, fading out over RAIL_FADE_MS: one picture (the note's cached shot)
and one fade per swap, nothing at all in between. The text re-wraps for the new width under that
fade, so it is never seen jumping."""
from __future__ import annotations

import time
import tkinter as tk

from PIL import Image, ImageTk

import winapi
import anim
from ui_common import RAIL_FADE_MS, RAIL_REST_MS, RAIL_W, PopupMenu, animate, fade, stop_animation


RAIL_SHOW_MS = 280               # the rail draws in from the left this long (asked for: quick, not a snap)
RAIL_HIDE_MS = 420               # ... and goes, out to the left fading into the page, this long (calm)
RAIL_STEPS = 16                  # ... fading into the page through this many cached pictures
RAIL_STAGGER_S = 0.05            # notes resting at once (start, the setting turned on) swap this far apart
RAIL_ARM_S = 0.25                # back on a hover: its buttons take clicks only after this (they came under
                                 # a pointer on its way to the text)


class CalmRail:
    def __init__(self, nw):
        self.nw, self.app = nw, nw.app
        self.hidden = False
        self._job = None
        self._shown_at = 0.0
        self._cover = None
        w = nw.win
        for seq in ("<FocusIn>", "<FocusOut>", "<Enter>", "<Leave>"):
            w.bind(seq, lambda e: self.check_soon(), add="+")

    # -- what the note is doing
    def _mine(self, top) -> bool:
        """``top`` is this note's window or its own calendar (using the calendar is using the note)."""
        cal = self.nw.calendar
        return top is self.nw.win or (cal is not None and top is cal.top)

    def _focused(self) -> bool:
        try:
            f = self.nw.win.focus_get()
        except (KeyError, tk.TclError):
            return False
        return f is not None and self._mine(f.winfo_toplevel())

    def _hovered(self) -> bool:
        w = self.nw.win
        try:
            x, y = w.winfo_pointerxy()
            under = w.winfo_containing(x, y)
        except (KeyError, tk.TclError):
            return False
        return under is not None and self._mine(under.winfo_toplevel())

    def _busy(self) -> bool:
        """Something of this note is up or moving: it never hides then."""
        nw, app = self.nw, self.app
        menu = PopupMenu.current
        try:
            return (app.moving or nw.rolling or nw._cover is not None or nw.toast.winfo_ismapped()
                    or app.motion.drives(nw.pad.id) or getattr(app, "tour", None) is not None
                    or nw._wide or (menu is not None and menu.owner.winfo_toplevel() is nw.win))
        except tk.TclError:
            return True

    def _quiet(self) -> bool:
        """The note is left alone: the setting on, the memo shown, the pointer elsewhere. (The pointer
        alone decides, the user's call after trying it: typing on with the mouse away, the rail rests
        too; the keys still do everything.)"""
        nw = self.nw
        if not self.app.prefs.rail_hide or nw.view != "home" or nw.pad.collapsed or nw._closing:
            return False
        return not self._hovered()

    def wanted(self) -> bool:
        """True: it should rest (left alone, and nothing of it up or moving)."""
        return self._quiet() and not self._busy()

    # -- deciding
    def check_soon(self):
        try:
            self.nw.win.after_idle(self.check)
        except tk.TclError:
            pass

    def check(self):
        """Back at once when wanted; resting RAIL_REST_MS after nothing wants it (checked again then).
        Closing or folded: left as it is (no rail coming back as the note fades out)."""
        nw = self.nw
        if nw._closing or nw.pad.collapsed or nw.rolling or nw.minimized:
            self._cancel()
            return
        if self.wanted():
            if not self.hidden and self._job is None:
                self._job = self.nw.win.after(RAIL_REST_MS, self._rested)
            return
        self._cancel()
        if self.hidden:
            self.show()

    def _rested(self):
        self._job = None
        if self.hidden or not self._quiet():
            return
        if self._busy():                    # a notice, a menu, a drag still up: looked at again later
            self._job = self.nw.win.after(RAIL_REST_MS, self._rested)    # (it ends without an event)
            return
        last = getattr(self.app, "_rail_swapped", 0.0)    # 5: many notes at once (start, the setting):
        now = time.monotonic()                              # one swap per STAGGER, not all in a tick
        if now - last < RAIL_STAGGER_S:
            self._job = self.nw.win.after(round(RAIL_STAGGER_S * 1000), self._rested)
            return
        self.app._rail_swapped = now
        self.hide()

    def _cancel(self):
        if self._job is not None:
            try:
                self.nw.win.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    # -- the swap
    def hide(self):
        self._swap(True)

    def show(self, cover=True):
        self._cancel()
        self._shown_at = time.monotonic()
        self._swap(False, cover)

    def armed(self) -> bool:
        """A rail button may act: not in the first RAIL_ARM_S after coming back (1: the click was
        meant for the text where the rail now is)."""
        return time.monotonic() - self._shown_at >= RAIL_ARM_S

    def _swap(self, hidden, cover=True):
        """The rail out of the layout (the memo takes its room) or back. Smooth first (the user's
        call): the rail slides out to the side fading into the page (or in from it) while the date
        row and the text glide over by its width; the dot, - and x and the grip stay where they are.
        All of it is pictures moved on a canvas in a click-through window over the note (no layout
        a frame); then that window fades off the live note (RAIL_FADE_MS), which has re-wrapped under
        it. Reduced: the fade only. Off, or a see-through note (a picture at its alpha over it would
        read more solid): at once."""
        nw = self.nw
        mode = self.app.clock.mode
        old = self._cover
        if old is not None and getattr(old, "step", None) is not None and mode == "full":
            self._reverse(old, hidden)      # turned back mid-slide: the same slide runs back, no jump
            return
        self._end_cover()
        use = cover and mode != "off" and nw.pad.alpha >= 0.995
        before = self._shot() if use else None
        geo = self._geometry() if before is not None else None
        rail_pic = None
        if before is not None and mode == "full" and geo is not None:
            if hidden:                      # (only the rail's strip is kept, for coming back: not the
                e, rw = geo[0], geo[1]      # whole note's picture, held per note for as long as it lives)
                rail_pic = before.crop((e, e, e + rw, before.size[1] - e))
                self._rail_cache = (rail_pic, (nw._rail_state, nw.colors.bg), before.size)
            else:
                cache = getattr(self, "_rail_cache", None)
                if (cache is not None and cache[1] == (nw._rail_state, nw.colors.bg)
                        and cache[2] == before.size):
                    rail_pic = cache[0]
        laid = False                        # (coming back without a kept picture of the rail: the fade
        self.hidden = hidden                # alone; one taken right after laying it out can show the old
                                            # layout, not painted yet: a strip of text sliding in)
        top = self._cover_window(before) if before is not None else None
        if top is None:
            if not laid:
                self._relayout(hidden)
            return
        self._cover = top
        if rail_pic is None:                # Reduced (or no picture of the rail): the fade alone
            if not laid:
                self._relayout(hidden)
            self._fade_off(top)
            return
        top.relayout = None if laid else hidden  # (done once the slide is over, under the still cover)
        self._slide(top, before, rail_pic, geo, hidden)

    def _relayout(self, hidden):
        """The note laid out for the rail in or out: packs or unpacks it, the date row and the pictures
        for the new width (pictures now, not 120 ms later)."""
        nw = self.nw
        self.hidden = hidden
        try:
            nw._sized(nw.win.winfo_width(), nw.win.winfo_height())
        except tk.TclError:
            return False
        nw.bump_look()                      # (its cached shot shows the other rail now)
        for key, redo in (("image", nw.viewer.render), ("inline", getattr(nw, "_rescale_inline", None))):
            job = nw._jobs.pop(key, None)
            if job is not None and redo is not None:
                nw.win.after_cancel(job)
                redo()
        return True

    def _slid(self, top):
        """The slide is over: the note is laid out under the cover (holding still at its last frame,
        so nothing that moves waits on it), then the cover fades off it."""
        if self._cover is not top:
            return
        if getattr(top, "relayout", None) is not None:
            hidden, top.relayout = top.relayout, None
            self._relayout(hidden)
        self._fade_off(top)

    def _reverse(self, top, hidden):
        """A swap the other way while the slide (or its fade) still shows: the layout goes back under
        the cover, and the slide runs back from where it is to where it started."""
        stop_animation(top.cv, "slide")
        stop_animation(top, "alpha")
        try:
            top.attributes("-alpha", min(self.nw.pad.alpha, 0.999))
        except tk.TclError:
            return
        if getattr(top, "relayout", None) is not None:
            top.relayout = None             # (the slide had not laid it out yet: it stays as it was)
            self.hidden = hidden
        elif not self._relayout(hidden):
            return
        k0 = top.k
        ms = RAIL_SHOW_MS if hidden else RAIL_HIDE_MS   # (back the way it came: that direction's pace)
        animate(top.cv, "slide", max(1, round(ms * k0)), lambda t: top.step(k0 * (1 - t)),
                lambda: self._fade_off(top), ease=lambda t: t, kind="move")

    def _shot(self):
        nw = self.nw
        try:
            if not nw.win.winfo_ismapped() or nw.win.state() != "normal":
                return None
            shot = self.app.shots.fresh(nw, keep=False)
        except (tk.TclError, ValueError, OSError):
            return None
        if shot is None:
            return None
        return shot if shot.mode == "RGB" else shot.convert("RGB")     # (only crops are taken from it: shared)

    def _geometry(self):
        """Where things are now, in the window's pixels: (edge, rail width, the top bar's bottom, the
        left of the right-hand piece (the dot, -, x), the grip's box or None)."""
        nw, px = self.nw, self.app.px
        try:
            wx, wy = nw.win.winfo_rootx(), nw.win.winfo_rooty()

            def box(w):
                x, y = w.winfo_rootx() - wx, w.winfo_rooty() - wy
                return x, y, x + w.winfo_width(), y + w.winfo_height()
            right = next((box(b)[0] for b in (nw.btn_color, nw.btn_min, nw.btn_close) if b.winfo_ismapped()),
                         nw.win.winfo_width() - nw.edge)
            grip = box(nw.grip) if nw.grip.winfo_ismapped() else None
            return nw.edge, px(RAIL_W), box(nw.bar)[3], right, grip
        except tk.TclError:
            return None

    def _cover_window(self, shot):
        """A click-through window over the note showing ``shot``."""
        nw = self.nw
        try:
            w, h = shot.size
            top = tk.Toplevel(nw.win)
            top.withdraw()
            top.overrideredirect(True)
            cv = top.cv = tk.Canvas(top, bd=0, highlightthickness=0, width=w, height=h, bg=nw.colors.bg)
            cv.pack(fill="both", expand=True)
            top.photos = [ImageTk.PhotoImage(shot, master=top)]
            cv.create_image(0, 0, anchor="nw", image=top.photos[0])
            top.geometry(f"{w}x{h}+{nw.win.winfo_rootx()}+{nw.win.winfo_rooty()}")
            top.attributes("-topmost", bool(nw.pad.pinned))
            top.deiconify()                 # a plain window while it slides: a layered one (see-through,
            if nw.edge == 0:                # click-through) is not shown again as its canvas changes, only
                winapi.clip_box(top, w, h, self.app.px(8))     # its corners rounded as the note's
            top.lift(nw.win)                # as its alpha does (seen in a recording: no slide, only the fade)
            top.update_idletasks()
            return top
        except (tk.TclError, ValueError, OSError):
            return None

    @staticmethod
    def _moving_text(before, box, grip, page):
        """The text's part of ``before`` (``box``), which slides by the rail's width. The grip stays
        put (its own piece, on top): its spot here is the page, or a second grip slides along with
        the text and stays on through the fade (the user saw it)."""
        img = before.crop(box)
        if grip is not None:
            gw, gh = grip[2] - grip[0], grip[3] - grip[1]
            if gw > 0 and gh > 0:
                img.paste(Image.new("RGB", (gw, gh), page), (grip[0] - box[0], grip[1] - box[1]))
        return img

    def _slide(self, top, before, rail_pic, geo, hidden):
        """The pieces of ``before`` on the cover, moved over RAIL_HIDE_MS or RAIL_SHOW_MS: the rail (``rail_pic``)
        out to the left fading into the page, or in from it; the date row and the text by the rail's
        width; the right-hand piece and the grip still. Then the cover fades off the live note."""
        nw, cv = self.nw, top.cv
        e, rw, row, right, grip = geo
        w, h = before.size
        page = nw.colors.bg
        cv.delete("all")
        photos = top.photos = []

        def put(img, x, y):
            photos.append(ImageTk.PhotoImage(img, master=top))
            return cv.create_image(x, y, anchor="nw", image=photos[-1])
        left = e + rw if hidden else e          # where the moving pieces start, in ``before``
        rail = rail_pic                         # (the rail's strip: e, e to e + rw, h - e)
        solid = Image.new("RGB", rail.size, page)
        ramp = [ImageTk.PhotoImage(Image.blend(rail, solid, i / (RAIL_STEPS - 1)), master=top)
                for i in range(RAIL_STEPS)]     # (the rail's fade, worked out once: a frame only picks one)
        photos.extend(ramp)
        rail_item = cv.create_image(e, e, anchor="nw", image=ramp[0])
        bar_img = before.crop((left, e, right, row))
        body_img = self._moving_text(before, (left, row, w - e, h - e), grip, page)
        bar_item = put(bar_img, left, e)
        body_item = put(body_img, left, row)
        put(before.crop((right, e, w - e, row)), right, e)        # the dot, -, x stay
        if grip is not None:
            put(before.crop(grip), grip[0], grip[1])               # the grip stays
        if e:                                                      # the window's own edge, kept on top
            cv.create_rectangle(0, 0, w - 1, h - 1, outline=nw.colors.frame, width=e)
        sign = -1 if hidden else 1

        def step(k):
            top.k = k                                              # (where it is: a turn back runs from here)
            top.frames = getattr(top, "frames", 0) + 1
            d = round(sign * rw * k)
            cv.coords(bar_item, left + d, e)
            cv.coords(body_item, left + d, row)
            out = k if hidden else 1 - k                           # 0: the rail as it is, 1: gone
            cv.coords(rail_item, e - round(rw * out), e)           # in from the left, out to the left (the
            cv.itemconfigure(rail_item, image=ramp[min(RAIL_STEPS - 1, round(out * (RAIL_STEPS - 1)))])
                                                                   # user's call): beside the text, never over it
        top.step = step
        top.frames = 0
        step(0.0)
        animate(cv, "slide", RAIL_HIDE_MS if hidden else RAIL_SHOW_MS, step, lambda: self._slid(top),
                ease=anim.smoothstep, kind="move")

    def _fade_off(self, top):
        """The cover fades off the live note: see-through (layered) and click-through from now on."""
        if self._cover is not top:
            return
        try:
            a0 = min(self.nw.pad.alpha, 0.999)
            top.attributes("-alpha", a0)
            winapi.set_click_through(top, True)
        except tk.TclError:
            self._end_cover()
            return
        fade(top, "alpha", a0, 0.0, RAIL_FADE_MS, done=self._end_cover)

    def _end_cover(self):
        cover, self._cover = self._cover, None
        if cover is not None:
            stop_animation(cover, "alpha")
            pending = getattr(cover, "relayout", None)
            if pending is not None and not self.nw._closing:    # cut short mid-slide (a drag, a minimize):
                cover.relayout = None                           # the note laid out as the rail now is
                self._relayout(pending)
            for name in ("photos", "step", "cv"):   # (they point back at it: a cycle the idle collect
                if hasattr(cover, name):            # frees late; its pictures go now)
                    setattr(cover, name, None)
            try:
                cover.destroy()
            except tk.TclError:
                pass

    def recolor(self):
        """(The note's colours changed: nothing kept here depends on them any more.)"""

    def close(self):
        self._cancel()
        self._end_cover()
        self._rail_cache = None
