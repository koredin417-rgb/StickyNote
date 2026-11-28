"""Phase 10, A and B (2026-11-28): the memo text's caret, drawn as a thin overlay over the text box
so it can glide to where the insert point goes (A) and breathe instead of blinking (B).

Tk's own caret is not drawn while the overlay shows (it keeps its width, so the Korean IME sees the
caret it always did and draws no box of its own: never off on 0 or on 0; just never on, in the page's
colour), and comes back whenever the
overlay cannot stand in for it: while the Korean IME composes a syllable (the note draws the
syllable itself at the insert point: NoteWindow._show_preedit), with a selection, without the
focus, on another page or folded. Nothing runs while the caret rests: a glide is one short run
on the frame clock; a breath is one too (out to the page and back on a sine, through cached
colours), then a plain timer rests it as long as Windows' own blink phase."""
from __future__ import annotations

import ctypes
import math
import time
import tkinter as tk

from ui_common import _mix, animate, stop_animation

CARET_GLIDE_MS = 70             # the overlay eases to the new insert point this fast (A)
CARET_BREATH = 12               # colour steps from the caret's colour to the page (B): smooth, cached
CARET_FAST_S = 0.1              # keys closer than this (a held Backspace, fast typing): it follows at once,
                                # no glide (a glide restarted every repeat trailed behind the text)
CARET_IDLE_MS = 5000            # no key or click this long: it stops breathing, solid (Windows' own
                                # caret timeout), so nothing runs while the note just sits there
GLIDE_KEY = "caret"             # its run on the frame clock
BREATH_KEY = "breath"           # a breath's run on the frame clock


def blink_ms() -> int | None:
    """Windows' caret blink time (ms a phase), or None when blinking is turned off."""
    try:
        ms = ctypes.windll.user32.GetCaretBlinkTime()
    except (AttributeError, OSError):
        return 530
    return None if ms in (0, 0xFFFFFFFF) or ms > 10000 else int(ms)


class GlideCaret:
    def __init__(self, nw):
        self.nw, self.body = nw, nw.body
        self.tk_width = max(1, int(self.body.cget("insertwidth")))
        self.frame = tk.Frame(self.body, width=self.tk_width, bd=0, highlightthickness=0)
        self.ramp = ["#000000"] * CARET_BREATH
        self._place = None              # (x, y, h) where it is now
        self._goal = None
        self._composing = False
        self._shown = False
        self._breath_job = None
        self._idle_job = None
        self._step = 0
        self._mouse = False             # the mouse put the insert point: Tk's own caret until a key
        self._since = 0.0               # when a key came last (breathing stops CARET_IDLE_MS after)
        self._dead = False
        self.tk_off = self.body.cget("insertofftime")
        self.tk_on = self.body.cget("insertontime")
        self.color, self.bg = "#000000", "#FFFFFF"
        blink = blink_ms()
        self.rest_ms = blink if blink is not None else 530
        self._breathes = blink is not None
        b = self.body
        for seq in ("<FocusIn>", "<FocusOut>", "<<Selection>>"):
            b.bind(seq, lambda e: self.follow_soon(), add="+")
        b.bind("<ButtonPress>", lambda e: self._pressed(), add="+")
        f = self.frame                  # (a press that lands on the 2 px overlay belongs to the text)
        for seq in ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>", "<ButtonPress-3>", "<ButtonRelease-3>"):
            f.bind(seq, lambda e, s=seq: self._forward(e, s))
        for seq in ("<Configure>", "<MouseWheel>"):
            b.bind(seq, lambda e: self.follow_soon(jump=True), add="+")
        # every key, on a binding tag of its own ahead of the text's: a key the text binds itself
        # (<BackSpace>, <Return>, <Delete>...) replaces the text's own <KeyPress> for that key, so a
        # held Backspace never told the caret and it stayed up to 10 characters behind (measured)
        self._key_tag = f"glidecaret{id(self)}"
        b.bind_class(self._key_tag, "<KeyPress>", lambda e: self.typed())
        b.bindtags((self._key_tag,) + tuple(b.bindtags()))

    # -- colours
    def _tk_caret(self, on):
        """Tk's own caret drawn (on) or not. Not: never "on" in its blink, in the page's colour; its width
        stays (a caret of width 0 makes the IME draw its own white box for the syllable)."""
        if on:
            self.body.configure(insertbackground=self.color, insertwidth=self.tk_width, insertontime=self.tk_on,
                                insertofftime=self.tk_off)
        else:                               # still drawn (Tk tells Windows where the caret is only as it draws
            self.body.configure(insertbackground=self.bg, insertwidth=1, insertontime=self.tk_on,   # it: the
                                insertofftime=0)    # IME then draws no box), but unseen: the page's colour,
                                                    # 1 px between two letters, steady (no blink)

    def recolor(self, color, bg):
        """The caret's colour and the page under it: the breathing ramp, cached."""
        self.color, self.bg = color, bg
        if self._shown:                     # (apply_look just set Tk's caret colour back)
            try:
                self._tk_caret(False)
            except tk.TclError:
                pass
        w = self.body
        self.ramp = [_mix(w, color, bg, i / (CARET_BREATH - 1)) for i in range(CARET_BREATH)]
        self._paint(self._step if self._breath_job else 0)

    def _paint(self, i):
        self._step = i
        try:
            if i == CARET_BREATH - 1:       # all the way out: gone, never a page-coloured bar over a glyph
                self.frame.place_forget()
                return
            self.frame.configure(bg=self.ramp[i])
            if self._shown and self._place is not None and not self.frame.winfo_ismapped():
                self._put(*self._place)
        except tk.TclError:
            pass

    # -- where it goes
    def _pressed(self):
        """The mouse puts the insert point: Tk's own caret (double-clicks and drags are Tk's),
        until a key (typing is where the glide is)."""
        self._mouse = True
        self._hide()

    def _forward(self, e, seq):
        self._mouse = True
        x, y = e.x + self.frame.winfo_x(), e.y + self.frame.winfo_y()
        self._hide()
        try:
            self.body.event_generate(seq, x=x, y=y, rootx=e.x_root, rooty=e.y_root, state=e.state)
        except tk.TclError:
            pass

    def _can_show(self) -> bool:
        nw, b = self.nw, self.body
        if self._mouse or self._dead:
            return False
        try:
            return (nw.view == "home" and not nw.pad.collapsed
                    and not nw._closing and b.focus_get() is b and not b.tag_ranges("sel")
                    and b.winfo_ismapped())
        except (KeyError, tk.TclError):
            return False

    def follow_soon(self, jump=False, now=False):
        """Follow once the key has done its work. ``now``: on a timer, not when idle (idle never
        comes while keys keep coming: under a held key it waited until the key was let go)."""
        if self._dead:
            return
        try:
            if self._idle_job is not None:
                self.body.after_cancel(self._idle_job)
            run = lambda: (setattr(self, "_idle_job", None), self.follow(jump))     # noqa: E731
            self._idle_job = self.body.after(1, run) if now else self.body.after_idle(run)
        except tk.TclError:
            pass

    def follow(self, jump=False):
        """Go where the insert point is: a glide (CARET_GLIDE_MS), or a jump when the view itself
        moved (``jump``), when it was hidden, or with Motion Off (the clock's "move" kind)."""
        box = self.body.bbox("insert") if self._can_show() else None
        if not box:
            self._hide()
            return
        x, y, _w, h = box
        if self._composing:                 # Korean: the syllable being put together shows at the
            pre = self.nw.preedit           # insert point (NoteWindow._show_preedit): the caret goes after it
            try:
                if pre.winfo_manager():
                    x += pre.winfo_reqwidth()
            except tk.TclError:
                pass
        line = self.body.dlineinfo("insert")
        if line:                        # the whole display line, as Tk's own caret
            y, h = line[1], line[3]
        x -= self.tk_width // 2
        goal = (x, y, h)
        if goal == self._goal and self._shown:
            return
        self._goal = goal
        start = self._place if (self._shown and not jump) else None
        self._show()
        if start is None or start == goal:
            stop_animation(self.frame, GLIDE_KEY)
            self._put(*goal)
            return
        x0, y0, h0 = start

        def step(k):
            self._put(x0 + (x - x0) * k, y0 + (y - y0) * k, h0 + (h - h0) * k)
        animate(self.frame, GLIDE_KEY, CARET_GLIDE_MS, step, kind="move")

    def _put(self, x, y, h):
        self._place = (round(x), round(y), round(h))
        try:
            self.frame.place(x=self._place[0], y=self._place[1], width=self.tk_width, height=self._place[2],
                             bordermode="ignore")      # (bbox counts from the outer edge)
        except tk.TclError:
            pass

    def _show(self):
        if not self._shown:
            self._shown = True
            try:
                self._tk_caret(False)               # (ours stands in for Tk's)
            except tk.TclError:
                return
            self._rest()

    def _hide(self):
        stop_animation(self.frame, GLIDE_KEY)
        self._cancel_breath()
        self._goal = None
        if self._shown:
            self._shown = False
            try:
                self.frame.place_forget()
                self._tk_caret(True)                # Tk's own again
            except tk.TclError:
                pass

    def composing(self, on: bool):
        """The IME is putting a syllable together (on) or done. The caret stays ours: just after the
        syllable shown at the insert point, gliding as it grows and as each one is done (Korean
        typing animates like any other, and Tk's own caret never shows before the syllable)."""
        if bool(on) != self._composing:
            self._composing = bool(on)
        self.follow()

    # -- breathing
    def typed(self):
        """A key: solid at once, breathing again after a rest; it follows where the key put it."""
        self._mouse = False
        now = time.monotonic()
        fast = now - self._since < CARET_FAST_S
        self._since = now
        self._rest()
        self.follow_soon(jump=fast, now=fast)

    def close(self):
        """The window goes: no timer of its own is left behind."""
        self._hide()
        self._dead = True
        try:
            self.body.unbind_class(self._key_tag, "<KeyPress>")
        except (AttributeError, tk.TclError):
            pass
        if self._idle_job is not None:
            try:
                self.body.after_cancel(self._idle_job)
            except tk.TclError:
                pass
            self._idle_job = None

    def _rest(self):
        self._cancel_breath()
        self._paint(0)
        if self._breathes and self.nw.app.clock.mode != "off":
            self._breath_job = self.body.after(self.rest_ms, self._breathe)

    def _cancel_breath(self):
        if self._breath_job is not None:
            if self._breath_job == BREATH_KEY:
                stop_animation(self.frame, BREATH_KEY)
            else:
                try:
                    self.body.after_cancel(self._breath_job)
                except tk.TclError:
                    pass
            self._breath_job = None

    def _breathe(self, i=0):
        """One breath: out to the page and back through the ramp in about a blink's time, then solid
        for a blink's time, then the next; CARET_IDLE_MS after the last key it stays solid and
        nothing runs."""
        if not self._shown or self.nw.app.clock.mode == "off":
            self._breath_job = None
            self._paint(0)
            return
        last = CARET_BREATH - 1

        def step(k):                    # out and back on one sine: no steps at the turn, no kick
            n = round(math.sin(math.pi * k) * last)
            if n != self._step:
                self._paint(n)

        def done():
            self._paint(0)              # back to solid: rest, or stop when the note sits idle
            if not self._shown or time.monotonic() - self._since > CARET_IDLE_MS / 1000:
                self._breath_job = None
                return
            self._breath_job = self.body.after(self.rest_ms, lambda: self._breathe(i + 1))
        self._breath_job = BREATH_KEY
        animate(self.frame, BREATH_KEY, self.rest_ms, step, done, ease=lambda t: t, kind="fade")
