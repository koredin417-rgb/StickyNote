"""Stand-in pictures of notes (the design's §5.3): one picture per note, kept while its look
holds, for the covers that stand in while a note rolls (fold, unfold, minimize, restore), while a
group resizes (NoteWindow.freeze), and for the delete fly.

A note's picture is current while its look version (NoteWindow.look_version, bumped whenever
what it shows changes), its size, its page and its scroll position are what they were when it
was taken. Notes in a linked group (they resize together) get theirs taken while the app is idle,
a couple at a time, so a group resize has them all at its first frame."""
from __future__ import annotations

import tkinter as tk

from PIL import Image

import winapi

WARM_PER_RUN = 2            # pictures taken per idle run (some 8 ms each: typing never waits long)
WARM_AGAIN_MS = 300         # ... then the next ones, if the app is still quiet


def capture(win) -> Image.Image | None:
    """``win`` as it shows now (PrintWindow, that window only), or None."""
    try:
        shot = winapi.snapshot(win) if win.winfo_ismapped() else None
    except tk.TclError:
        return None
    if shot is None:
        return None
    w, h, data = shot
    return Image.frombuffer("RGB", (w, h), data, "raw", "BGRX", 0, 1).copy()


class ShotCache:
    def __init__(self, app):
        self.app = app
        self._shots: dict = {}          # pad id -> (key, image)
        self._stale: set = set()        # linked notes whose picture is to be taken when idle
        self._armed = False

    @staticmethod
    def _key(nw, size=None):
        try:
            w, h = size or (nw.win.winfo_width(), nw.win.winfo_height())
            top = nw.body.yview()[0] if nw.view == "home" else None
        except tk.TclError:
            return None
        return nw.look_version, w, h, nw.view, top

    def peek(self, nw, size=None) -> Image.Image | None:
        """Its picture if it is still current (at ``size``: (w, h), default the window's), else None."""
        entry = self._shots.get(nw.pad.id)
        if entry is None or entry[0] is None or entry[0] != self._key(nw, size):
            return None
        return entry[1]

    def shot(self, nw) -> Image.Image | None:
        """Its picture as it shows now: the kept one if still current, else taken now."""
        img = self.peek(nw)
        if img is not None:
            return img
        img = capture(nw.win)
        if img is not None:
            self._shots[nw.pad.id] = (self._key(nw), img)
            self._stale.discard(nw.pad.id)
        return img

    def drop(self, nw) -> None:
        """The window closes: its picture goes."""
        self._shots.pop(nw.pad.id, None)
        self._stale.discard(nw.pad.id)

    # ---- taken ahead, when idle
    def stale(self, nw) -> None:
        """``nw``'s look changed. A note in a linked group gets a new picture once the app is quiet."""
        if len(self.app.group_of(nw.pad.id)) < 2:
            return
        self._stale.add(nw.pad.id)
        if not self._armed:
            self._armed = True
            self.app.clock.idle(self._warm)

    def _ready(self, nw) -> bool:
        try:
            return (not nw._closing and not nw.minimized and not nw.rolling and nw._cover is None
                    and not nw.pad.collapsed and nw.view == "home" and nw.win.state() == "normal"
                    and nw.win.winfo_ismapped())
        except tk.TclError:
            return False

    def _warm(self) -> None:
        self._armed = False
        taken = 0
        for pid in list(self._stale):
            nw = self.app.windows.get(pid)
            if nw is None:
                self._stale.discard(pid)
                continue
            if not self._ready(nw):
                continue                    # (again when it is: its next look change re-arms)
            if self.peek(nw) is None:
                self.shot(nw)
                taken += 1
            self._stale.discard(pid)
            if taken >= WARM_PER_RUN:
                break
        if self._stale and taken:
            self._armed = True
            self.app.root.after(WARM_AGAIN_MS, self._again)

    def _again(self) -> None:
        if self.app.clock.busy:             # (moving again: once it is quiet)
            self.app.clock.idle(self._warm)
        else:
            self._warm()
