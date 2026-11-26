"""Every move the app makes by itself goes through Motion (S4: one plan, one glide).

An action works out its final boxes once and hands them to ``Motion.run`` (through
``App.apply`` / ``App.apply_plan``). Every changed window, the notes and the calendar, then
glides there once, all on the app's one frame clock (anim.FrameClock): a "box" tween per window.
A note whose size changes is frozen (a still picture stands in: NoteWindow.freeze) and thawed
when it gets there. The end-of-action hooks (settle_links, request_save, ``done``) run once,
when the last window has landed.

Ids are pad ids or CAL (the calendar, docked or not). A window is where its pad says while it
is settled, and at ``item.now`` while it moves; the pad's ``target`` and size are its
destination from the start, so space() sees it there (S1), and its x/y are written at the end.

Also Outlines: the dashed outlines live drags show where things will go (one click-through
window that takes no space).
"""
from __future__ import annotations

import time
import tkinter as tk

import winapi
from geom import CAL, pad_box, shown_h
from ui_common import GLIDE_MS, TIP_KEY, _alpha, accent_color, animating, stop_animation

# A click-through window keeps -alpha below 1.0 while it is click-through, so Tk layers it
# itself (see winapi.set_click_through). 0.999 looks fully opaque.
CLICK_THROUGH_ALPHA = 0.999
CROSSFADE_MS = 60               # Animations: Reduced: a moving window fades out this fast, jumps, fades back


def _size(b):
    return b[2] - b[0], b[3] - b[1]


def _sweeps_over(start, end, note_start, note_end) -> bool:
    """A calendar gliding from ``start`` to ``end`` (it has ``end``'s size on the way) would pass over
    its note (gliding from ``note_start`` to ``note_end`` on the same clock): it changes sides."""
    w, h = end[2] - end[0], end[3] - end[1]
    for k in (0.2, 0.35, 0.5, 0.65, 0.8):
        x, y = start[0] + (end[0] - start[0]) * k, start[1] + (end[1] - start[1]) * k
        n = [a + (b - a) * k for a, b in zip(note_start, note_end)]
        if x < n[2] - 1 and n[0] + 1 < x + w and y < n[3] - 1 and n[1] + 1 < y + h:
            return True
    return False


def _lerp(a, b, k):
    return tuple(round(p + (q - p) * k) for p, q in zip(a, b))


class _Item:
    """One window gliding from the box ``start`` to the box ``end``, over ``ms`` from ``t0``;
    ``now`` is the box it was last put at. ``sized``: a note's size changes on the way (it is
    frozen); for CAL, its size was changed at the start (only its place glides). ``pad``: a
    note's Pad (it outlives its window: set_language, closing)."""
    __slots__ = ("id", "start", "end", "now", "t0", "ms", "sized", "pad")

    def __init__(self, item_id, start, end, t0, ms, sized, pad=None):
        self.id, self.start, self.end, self.now = item_id, start, end, start
        self.t0, self.ms, self.sized, self.pad = t0, ms, sized, pad


class Motion:
    def __init__(self, app):
        self.app = app
        self._items: dict[str, _Item] = {}      # what is gliding, by id (a later plan's item replaces it)
        self._dones: list = []                  # the done() of every plan since the last end, in order
        self._arrived: list = []                # items whose glide got there, landed at the next frame
        self._fading: dict = {}                 # id -> item cross-fading (Animations: Reduced)

    # ---- asking ------------------------------------------------------------------------
    def busy(self) -> bool:
        return bool(self._items)

    def loops(self) -> int:
        """1 while glides run (on the app's frame clock), else 0."""
        return 1 if self._items else 0

    def drives(self, pid) -> bool:
        """``pid`` (a pad id or CAL) is in the running plan."""
        return pid in self._items

    # ---- the windows ---------------------------------------------------------------------
    def _note(self, pid):
        nw = self.app.windows.get(pid)
        try:
            return nw if nw is not None and nw.win.winfo_exists() else None
        except tk.TclError:
            return None

    def _calendar(self):
        """The open calendar (one at a time), unless it is closing."""
        cal = next((w.calendar for w in self.app.windows.values() if w.calendar is not None), None)
        if cal is None or getattr(cal, "_closing", False):
            return None
        try:
            return cal if cal.top.winfo_exists() else None
        except tk.TclError:
            return None

    def _opening(self):
        """The calendar being opened (its Toplevel still withdrawn), else None."""
        cal = self._calendar()
        try:
            return cal if cal is not None and cal.top.state() == "withdrawn" else None
        except tk.TclError:
            return None

    def _here(self, pid):
        """Where the window is now: its item's box while it moves, else its pad's (the
        calendar's target_box). None: there is no such window to move."""
        item = self._items.get(pid)
        if item is not None:
            return item.now
        if pid == CAL:
            cal = self._calendar()
            return None if cal is None or cal.target_box is None else tuple(cal.target_box)
        nw = self._note(pid)
        if nw is None or nw.pad.x is None or nw.pad.y is None:
            return None
        p = nw.pad
        return p.x, p.y, p.x + p.width, p.y + shown_h(p)

    @staticmethod
    def _follow(cal, old, new):
        """Where a docked calendar at ``cal.target_box`` goes when its note goes from the box
        ``old`` to ``new``: on the same side, as far from it; beside it and as tall as it, it
        stays as tall as the note (C1), never below its own least height (#20A)."""
        cb = tuple(cal.target_box)
        w, h = _size(cb)
        right, left = cb[0] >= old[2], cb[2] <= old[0]
        if right:
            x = new[2] + cb[0] - old[2]
        elif left:
            x = new[0] - (old[0] - cb[2]) - w
        else:
            x = cb[0] + new[0] - old[0]
        if not (right or left) and cb[1] >= old[3]:
            y = new[3] + cb[1] - old[3]
        elif not (right or left) and cb[3] <= old[1]:
            y = new[1] - (old[1] - cb[3]) - h
        else:
            y = new[1] if right or left else cb[1] + new[1] - old[1]     # beside it: tops lined up (C1)
        if (right or left) and not cal.nw.pad.collapsed and h == old[3] - old[1]:
            h = max(new[3] - new[1], cal.least[1] if cal.least else h)
        return x, y, x + w, y + h

    # ---- running a plan --------------------------------------------------------------------
    def run(self, targets, ms=GLIDE_MS, done=None, starts=None) -> None:
        """Glide every id in ``targets`` (pad ids or CAL -> boxes) to its box, on the one
        clock. ``starts``: an id's start top-left when its window is not where it is now (a
        new note sliding out from behind its parent). A note's docked calendar not in
        ``targets`` goes along beside it. An id still gliding from an earlier plan is taken
        over from where it is (a later plan wins); that plan's other ids glide on. The end
        step (settle_links, request_save, then each plan's ``done``) runs once, when nothing
        moves any more."""
        app, starts = self.app, dict(starts or {})
        plan = {}
        opening = self._opening()
        for pid, b in targets.items():
            here = self._here(pid)
            if pid == CAL and opening is not None:      # still withdrawn: its plan's box, no frames (reveal() shows it)
                opening.target_box = tuple(int(round(v)) for v in b)
                if opening.docked:
                    nx, ny = pad_box(opening.nw.pad)[:2]
                    opening._dock_offset = (opening.target_box[0] - nx, opening.target_box[1] - ny)
                app.space_changed()
                continue
            if here is None:
                continue
            end = tuple(int(round(v)) for v in b)
            if pid != CAL:
                p = app.windows[pid].pad
                if p.collapsed:                 # folded: as tall as its top bar, whatever the box says
                    end = end[:3] + (end[1] + shown_h(p),)
            plan[pid] = (here, end)
        cal = self._calendar()
        if (cal is not None and opening is None and CAL not in plan and cal.docked and cal.target_box is not None
                and cal.nw.pad.id in plan):     # the docked calendar goes along (_on_configure no longer places it)
            note_end = plan[cal.nw.pad.id][1]
            plan[CAL] = (self._here(CAL), self._follow(cal, pad_box(cal.nw.pad), note_end))
        jump_cal = None                     # a docked calendar changing sides: no glide across its note
        if CAL in plan and cal is not None and opening is None and cal.docked and CAL not in starts:
            owner = cal.nw.pad.id
            n0, n1 = plan[owner] if owner in plan else (pad_box(cal.nw.pad),) * 2
            s, e = plan[CAL]
            if _sweeps_over(s, e, n0, n1):
                jump_cal = e
                plan[CAL] = ((e[0], e[1], e[0] + s[2] - s[0], e[1] + s[3] - s[1]), e)
                try:
                    stop_animation(cal.top, "alpha")
                    cal.top.attributes("-alpha", 0.0)       # hidden while it jumps; it fades in there
                except tk.TclError:
                    jump_cal = None
        for pid, (sx, sy) in starts.items():
            if pid in plan:
                here, end = plan[pid]
                plan[pid] = ((int(sx), int(sy), int(sx) + here[2] - here[0], int(sy) + here[3] - here[1]), end)

        t0, new, superseded = time.perf_counter(), [], set()     # (t0 is set again below)
        for pid, (start, end) in plan.items():
            old = self._items.get(pid)
            if old is not None and old.end == end and pid not in starts:
                continue                        # going there already: its glide goes on
            if pid == CAL:
                sized = _size(start) != _size(end)
                start = start[:2] + (start[0] + end[2] - end[0], start[1] + end[3] - end[1])
            else:
                p = app.windows[pid].pad
                sized = start[2] - start[0] != end[2] - end[0] or (
                    not p.collapsed and start[3] - start[1] != end[3] - end[1])
            if old is not None:
                del self._items[pid]
                superseded.add(pid)
            if start == end and not (pid == CAL and sized):
                if old is not None:             # stopped right where it now goes
                    self._stop_glide(pid)
                    self._land(pid, end, old.sized, old.pad)
                elif pid != CAL:                # there already (its pad may say otherwise: starts)
                    self._settle(app.windows[pid].pad, end)
                continue
            pad = None if pid == CAL else app.windows[pid].pad
            item = self._items[pid] = _Item(pid, start, end, t0, ms, sized, pad)
            new.append(item)
        for item in sorted(new, key=lambda i: i.id == CAL):     # (notes first: CAL's offset is from its note)
            self._begin(item, item.id in superseded, item.id in starts)
        if jump_cal is not None:
            if CAL not in self._items:          # same size: nothing glides, so it is put there now
                cal.move_to(jump_cal)
            cal.apply_alpha(animated=True)      # fades in at its new side
        if new or superseded:
            app.space_changed()
        if done is not None:
            self._dones.append(done)
        if not self._items:                     # nothing (left) to move: the action ends here
            self._end()
            return
        for item in new:                        # last: drawing may run idle tasks (and a plan in them)
            if item.id == CAL and item.sized and self._items.get(CAL) is item:
                self._resize_calendar(item)
        for item in sorted(new, key=lambda i: i.id == CAL):    # the glides start once all are ready
            if self._items.get(item.id) is item:                # (freezing a dozen notes takes a while)
                self._glide(item)

    def _window(self, pid):
        if pid == CAL:
            cal = self._calendar()
            return None if cal is None else cal.top
        nw = self._note(pid)
        return None if nw is None else nw.win

    def _glide(self, item):
        """The item's frames, on the app's frame clock: a "box" tween of its window. One already
        gliding (an earlier plan) turns toward the new box from where it is, at its speed."""
        win = self._window(item.id)
        if win is None:
            return
        cal = self._calendar() if item.id == CAL else None
        if self.app.clock.mode == "reduced":    # Animations: Reduced: it fades out, jumps, fades in
            self._crossfade(item, win, cal)
            return

        def extra(b, item=item):
            item.now = b
            if cal is not None:
                cal._xy = (b[0], b[1])
        self.app.clock.glide(win, item.end, item.ms, frm=item.start, sized=item.sized and item.id != CAL,
                             write_extra=extra, done=lambda item=item: self._got_there(item))

    def _crossfade(self, item, win, cal):
        """Animations: Reduced: the window fades out, jumps to its box, fades back. It runs on the
        window's own "box" key, like a glide (a cancel, a finish or a later plan stops it the same
        way, and puts the window's opacity back); the opacity is written here, not by a fade."""
        clock = self.app.clock
        clock.stop(win, "alpha")
        a0, jumped = _alpha(win), [False]
        self._fading[item.id] = item

        def step(k):
            if k < 0.5:
                win.attributes("-alpha", a0 * (1 - 2 * k))
                return
            if not jumped[0]:
                jumped[0] = True
                self._show(item, 1.0)
            win.attributes("-alpha", self._alpha_back(item.id, item) * (2 * k - 1))

        def done():
            self._fading.pop(item.id, None)
            self._got_there(item)
        clock.animate(win, "box", 2 * CROSSFADE_MS, step, done, ease=lambda t: t)

    def _alpha_back(self, pid, item):
        if pid == CAL:
            cal = self._calendar()
            return cal._target_alpha() if cal is not None else 1.0
        return item.pad.alpha if item.pad is not None else 1.0

    def fading(self, pid) -> bool:
        """``pid`` is cross-fading (Animations: Reduced): its opacity is the cross-fade's."""
        return pid in self._fading

    def _stop_glide(self, pid):
        win = self._window(pid)
        if win is not None:
            self.app.clock.stop(win, "box")
        item = self._fading.pop(pid, None)
        if item is not None and win is not None:    # stopped mid cross-fade: as see-through as it should be
            try:
                win.attributes("-alpha", self._alpha_back(pid, item))
            except tk.TclError:
                pass

    def _got_there(self, item):
        """A glide's last frame: it lands at the start of the next frame, with the others that
        got there (notes first, so the calendar's offset is from its note's final box)."""
        if self._items.get(item.id) is item:
            self._arrived.append(item)
            self.app.clock.request(self._land_arrived)

    def _land_arrived(self):
        arrived, self._arrived = self._arrived, []
        landed = []
        for item in arrived:
            if self._items.get(item.id) is item:
                del self._items[item.id]
                landed.append(item)
        self._land_all(landed)
        if landed and not self._items:          # (nothing landed: whoever stopped them ends the action)
            self._end()

    def window_gone(self, pid):
        """``pid``'s window is closing: its glide stops; the pad keeps where it got. The action's
        end step runs if nothing else moves."""
        item = self._items.pop(pid, None)
        if item is None:
            return
        self._stop_glide(pid)
        self._land(pid, item.now, False, item.pad)
        if not self._items:
            self._end()

    def _begin(self, item, superseded, jump):
        """An item's first step: its destination is known at once (S1), a note whose size
        changes is frozen, and one taken over from an earlier plan that keeps its size is thawed."""
        if item.id == CAL:
            cal = self._calendar()
            # (still sliding out: the glide is the same "box" tween, so it turns from there)
            cal.target_box = item.end
            if cal.docked:                      # (follow_note keeps it beside its note's destination)
                nx, ny = pad_box(cal.nw.pad)[:2]
                cal._dock_offset = (item.end[0] - nx, item.end[1] - ny)
            if jump:
                self._show(item, 0.0)
            return
        nw = self.app.windows[item.id]
        p, (x0, y0, x1, y1) = nw.pad, item.end
        p.target = (x0, y0)
        p.width = x1 - x0
        if not p.collapsed:                     # folded: pad.height is the unfolded height, kept
            p.height = y1 - y0
        if item.sized:
            nw.freeze()                         # (already frozen by the plan it took over: kept)
        elif superseded:
            nw.thaw()
        if jump:
            self._show(item, 0.0)

    def _settle(self, p, b):
        """A note not moving at all whose pad is not at its box (the window is): the pad is."""
        x0, y0, x1, y1 = b
        if (p.x, p.y, p.width) != (x0, y0, x1 - x0) or (not p.collapsed and p.height != y1 - y0):
            p.x, p.y, p.width = x0, y0, x1 - x0
            if not p.collapsed:
                p.height = y1 - y0
            self.app.space_changed()

    def _resize_calendar(self, item):
        """CAL changes size: it takes the new size (and is drawn for it) at the start; then
        its place glides."""
        cal = self._calendar()
        if cal is None:
            return
        w, h = _size(item.end)
        cal.fit_size = (w, h)
        cal.draw()
        x, y = item.now[:2]
        cal.top.geometry(f"{w}x{h}+{x}+{y}")
        cal.least = cal.least_size()            # (measured here, outside the frame loop: move_to reads no idle)

    def _show(self, item, k) -> bool:
        """Put the item's window at ``k`` (0..1, eased) of the way. False: its window is gone."""
        b = item.end if k >= 1.0 else _lerp(item.start, item.end, k)
        try:
            if item.id == CAL:
                cal = self._calendar()
                if cal is None:
                    return False
                cal.top.geometry(f"+{b[0]}+{b[1]}")
                cal._xy = (b[0], b[1])
            else:
                nw = self._note(item.id)
                if nw is None:
                    return False
                if item.sized:
                    nw.win.geometry(f"{b[2] - b[0]}x{b[3] - b[1]}+{b[0]}+{b[1]}")
                else:
                    nw.win.geometry(f"+{b[0]}+{b[1]}")
        except tk.TclError:
            return False
        item.now = b
        return True

    def _land_all(self, items):
        for item in sorted(items, key=lambda i: i.id == CAL):  # notes first: the calendar's offset is from its note
            if item.id not in self._items:      # (a plan started meanwhile has it now: that one lands it)
                self._land(item.id, item.end, item.sized, item.pad)

    def _land(self, pid, b, sized, pad=None):
        """An item's own end (also for one a later plan took over, or one stopped): the pad gets
        the box, the picture goes, the calendar is put there (move_to). No hooks: see _end.
        ``pad``: a note's pad, settled even when its window has gone."""
        if pid == CAL:
            cal = self._calendar()
            if cal is not None:
                cal.move_to(b)
        else:
            nw = self._note(pid)
            p = nw.pad if nw is not None else pad
            if p is None:
                return
            p.x, p.y, p.width = b[0], b[1], b[2] - b[0]
            if not p.collapsed:
                p.height = b[3] - b[1]
            p.target = None
            if nw is not None:
                nw.thaw()
                if sized:
                    nw._sized(p.width)
        self.app.space_changed()

    def _end(self):
        """The end of the action, once nothing moves: links settle (M2), it is saved, then each
        plan's done(), in the order they were run. Never at a superseded plan's in-between boxes."""
        if self._items:
            return                              # (a plan started while the last ones landed)
        dones, self._dones = self._dones, []
        self.app.settle_links()
        self.app.request_save()
        for done in dones:
            done()

    # ---- stopping --------------------------------------------------------------------------
    def cancel(self, ids) -> None:
        """Stop these where they are now (the user takes hold of a sliding note): thawed, no
        pad.target, the pad (or the calendar) gets where it is. A note's docked calendar stops
        with it. When nothing is left moving, the action's end step does not run (whoever took
        hold ends it)."""
        ids = set(ids)
        cal = self._calendar()
        if cal is not None and cal.docked and cal.nw.pad.id in ids:
            ids.add(CAL)
        stopped = [self._items.pop(pid) for pid in list(self._items) if pid in ids]
        if not stopped:
            return
        for item in sorted(stopped, key=lambda i: i.id == CAL):
            self._stop_glide(item.id)
            self._land(item.id, item.now, item.sized, item.pad)
        if not self._items:
            self._dones = []

    def finish(self) -> None:
        """Everything jumps to its box now, and the end step runs."""
        items = list(self._items.values())
        if not items and not self._dones:
            return
        self._items.clear()
        self._arrived = []
        for item in items:
            self._stop_glide(item.id)
            self._show(item, 1.0)
        self._land_all(items)
        self._end()


class Outlines:
    """Dashed outlines showing where things will go (the live drags). One topmost window over
    the boxes that clicks pass through (winapi.set_click_through) and that takes no space:
    space() lists notes and the calendar only."""

    def __init__(self, app):
        self.app, self.boxes, self._through = app, [], False
        t = self.top = tk.Toplevel(app.root)
        t.withdraw()
        t.overrideredirect(True)
        t.configure(bg=TIP_KEY)
        try:
            t.attributes("-transparentcolor", TIP_KEY)     # only the lines show
        except tk.TclError:
            pass
        t.attributes("-alpha", CLICK_THROUGH_ALPHA)         # Tk layers it (set_click_through's rule)
        t.attributes("-topmost", True)
        self.cv = tk.Canvas(t, bg=TIP_KEY, bd=0, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)

    def show(self, boxes) -> None:
        self.boxes = [tuple(int(v) for v in b) for b in boxes]
        if not self.boxes:
            self.hide()
            return
        px = self.app.px
        lw = max(1, px(2))
        m = lw + px(1)
        x0, y0 = min(b[0] for b in self.boxes) - m, min(b[1] for b in self.boxes) - m
        x1, y1 = max(b[2] for b in self.boxes) + m, max(b[3] for b in self.boxes) + m
        color = accent_color(self.top, self.app.theme_colors().bg, "#FFFFFF")
        self.cv.delete("all")
        for b in self.boxes:
            self.cv.create_rectangle(b[0] - x0, b[1] - y0, b[2] - x0, b[3] - y0, outline=color, width=lw,
                                     dash=(px(6), px(4)))
        self.top.geometry(f"{x1 - x0}x{y1 - y0}+{x0}+{y0}")
        if self.top.state() != "normal":
            self.top.deiconify()
        if not self._through:                   # after its first map (it has a frame window then)
            self.top.update_idletasks()
            winapi.set_click_through(self.top, True)
            self._through = bool(winapi.hwnd_of(self.top))

    def hide(self) -> None:
        try:
            if self.top.state() != "withdrawn":     # (asked at every frame of a live resize)
                self.top.withdraw()
        except tk.TclError:
            pass
