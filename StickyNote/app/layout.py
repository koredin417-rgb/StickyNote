"""The space model and its plans: what takes up room, where a note goes, growing, closing up, giving room back, dropping, applying a plan with Undo, folding. (Part of App: see app.py.)"""
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

import calgeom
import geom
import grid
import holidays
import space
import store as _store
import texts
import anim
import gc
import perf
import winapi
from geom import Box, Screen
from icon import draw_icon
from links import Links, links_from_touching
from motion import Motion, Outlines
from shots import ShotCache
from waker import Waker
from store import (BIN_DAY_CHOICES, CURSOR_COLORS, CUSTOM_COLORS, EMPTY_TITLE, INLINE, LIST_SORTS, MARK_KINDS,
                   PIN_LIMIT_MAX, SNAP_GAPS, SOLID_COLORS, STYLES, TIDY_ORDERS, Note, NoteStore, Pad, Prefs)
from texts import tr
from ui_note import *  # noqa: F401,F403  (all parts of the UI: ui_common … ui_note)


# --------------------------------------------------------------------------- app
from appbase import *  # noqa: F401,F403


class LayoutMixin:
    def space_changed(self):
        """Something that takes up space came, went, moved, changed size or changed state:
        the next space() builds the list again (and the taskbar preview is looked at)."""
        self._space_epoch += 1
        thumb = getattr(self, "thumb_soon", None)
        if thumb is not None:
            thumb()

    def space(self, exclude=()) -> list[space.Shape]:
        """S1, every shape that takes up space, each where it is going (at its destination
        while it glides):
        - every shown note (not minimized, not closing): kind "note", its pad box;
        - a note with its docked calendar: one "pair" (see _shape);
        - the undocked calendar: CAL, kind "cal", at its target_box;
        - the room minimized notes keep (held_room): kind "held".
        A calendar is listed (in a pair or as CAL) only once it has a target_box, and not while
        it closes. ``exclude``: ids left out; leaving out CAL makes a pair its plain note.
        The list is built once per _space_epoch (space_changed) from the pads and the
        calendar's caches (target_box, least) alone: it never measures a window."""
        if self._space_cache is None or self._space_cache[0] != self._space_epoch:
            self._space_cache = (self._space_epoch, self._build_space())
        shapes = self._space_cache[1]
        exclude = set(exclude)
        if not exclude:
            return list(shapes)
        return [space.Shape(s.id, s.parts[0], stacked=s.stacked) if s.kind == "pair" and CAL in exclude else s
                for s in shapes if s.id not in exclude and s.id.removesuffix("/cal") not in exclude]

    def _build_space(self) -> list[space.Shape]:
        notes, cals = [], []
        for nw in self.windows.values():
            try:
                shown = not nw._closing and nw.win.state() == "normal"
            except tk.TclError:                     # (a window being rebuilt: set_language)
                shown = False
            if not shown:
                cal = nw.calendar               # a calendar left on its own (its note minimized)
                if nw.minimized and cal is not None and not cal.docked and _placed(cal):
                    cals.append(space.Shape(CAL, tuple(cal.target_box), kind="cal", least=cal.least))
                continue
            notes.append(self._shape(nw))
            cal = nw.calendar
            if cal is not None and not cal.docked and _placed(cal):
                cals.append(space.Shape(CAL, tuple(cal.target_box), kind="cal", least=cal.least))
        held = [space.Shape(pad_id, tuple(b), kind="held") for pad_id, b in self.held_room.items()]
        for pad_id, cb in ([] if self.prefs.auto_layout else list(self._held_cal.items())):
            nw = self.windows.get(pad_id)              # (C4: auto layout holds nothing: the tiles re-flow)
            if nw is None:
                continue
            note, cb = _pad_box(nw.pad), tuple(cb)
            if nw.pad.calendar_docked:
                held.append(space.Shape(pad_id, geom.union([note, cb]), kind="held", parts=(note, cb)))
            else:
                held += [space.Shape(pad_id, note, kind="held"), space.Shape(f"{pad_id}/cal", cb, kind="held")]
        return notes + cals + held

    def shape_of(self, nw) -> space.Shape:
        """``nw``'s shape as space() lists it: its pad box, or the pair with its docked calendar
        (whether or not it is shown)."""
        return self._shape(nw)

    def _shape(self, nw) -> space.Shape:
        """The note alone, or with its docked (and placed) calendar as a "pair": ``box`` their
        union, ``parts`` (note, calendar), ``side`` where the calendar is, ``cal_least`` the
        calendar's least size and ``least`` the pair's (R4: split_pair keeps the calendar's
        current size on the shared axis, so that is the calendar's size there, not its least)."""
        p = nw.pad
        note = _pad_box(p)
        cal = nw.calendar
        if cal is None or not cal.docked or not _placed(cal):
            return space.Shape(p.id, note, stacked=p.stacked)
        cb = tuple(cal.target_box)
        side = _side_of(note, cb)
        cal_least = tuple(cal.least) if cal.least else (cb[2] - cb[0], cb[3] - cb[1])
        gap, px = self._gap(), self.px
        if side in ("right", "left"):
            least = (px(MIN_W) + gap + cb[2] - cb[0], max(px(MIN_H), cal_least[1]))
        else:
            least = (max(px(MIN_W), cal_least[0]), px(MIN_H) + gap + cb[3] - cb[1])
        return space.Shape(p.id, geom.union([note, cb]), kind="pair", stacked=p.stacked, parts=(note, cb),
                           side=side, least=least, cal_least=cal_least)

    def find_spot(self, w, h, origin, exclude=(), avoid: tuple = ()) -> tuple[Box, str]:
        """Where a ``w`` x ``h`` box that wants its top-left at ``origin`` goes, clear of
        space(exclude), and how:
        - "free": the nearest free spot (S2, S3), on origin's screen first;
        - "shrunk": else the nearest one for it made smaller, down to MIN_W x MIN_H (P5 step 1);
        - "piled": else the overflow pile on origin's screen, in the corner farthest from the
          calendar and keeping its cycles off it (P5 step 2), past every member already on it
          (a stacked pair counts by its note's box). A spot hanging past the area (a cycle
          longer than it) is trimmed to it, but never below MIN_W x MIN_H (R3).
        It sets nothing on any pad: callers hand the result to take_spot."""
        shapes = self.space(exclude)
        avoid = tuple(tuple(b) for b in avoid)      # boxes planned in this action that space() doesn't show yet
        obstacles = [s.box for s in shapes] + list(avoid)
        screens, gap, px = self.screens(), self._gap(), self.px
        areas = geom.usable(screens, gap)
        x, y = origin
        home = geom.screen_of((x, y, x + w, y + h), screens)
        spot = space.nearest_free(w, h, origin, areas, obstacles, gap, home)
        if spot is not None:
            return spot, "free"
        spot = space.shrink_to_fit(w, h, px(MIN_W), px(MIN_H), origin, areas, obstacles, gap, home)
        if spot is not None:
            return spot, "shrunk"
        area, step = areas[home], px(PILE_STEP)
        cal = next((s.parts[1] if s.kind == "pair" else s.box      # (where it is, even if left out above)
                    for s in self.space() if s.kind in ("pair", "cal")), None)
        corner, keep_off = space.pile_corner(area, cal), (() if cal is None else (cal,)) + avoid     # (and keep off it)
        members = [s.parts[0] if s.kind == "pair" else s.box        # a pair's note is what sits on a spot
                   for s in shapes if s.stacked and geom.screen_of(s.box, screens) == home]
        loose = tuple(s.box for s in shapes if not s.stacked)       # the top bars of the notes off the pile stay clear
        for keep in (keep_off + loose, keep_off):                   # ... unless that would restart the pile over its members
            start = space.pile_start(members, (w, h), area, corner, step, avoid=keep)
            x0, y0, x1, y1 = space.pile_spots([(w, h)], area, corner, step, start=start, before=members,
                                              avoid=keep)[0]
            if not any(geom.overlap((x0, y0, x1, y1), m) for m in members):
                break
        if x1 > area[2] and area[2] - x0 >= min(px(MIN_W), w):     # (it never hangs before the start)
            x1 = area[2]
        if y1 > area[3] and area[3] - y0 >= min(px(MIN_H), h):
            y1 = area[3]
        return (x0, y0, x1, y1), "piled"

    def take_spot(self, pad: Pad, spot, how):
        """What every caller does with find_spot's result: the pad takes the spot's box (a
        folded note keeps its own height); it is stacked only when piled (P5); and when the
        spot is smaller than the note, the note keeps its own size from before, once (P6)."""
        x0, y0, x1, y1 = spot
        w, h = x1 - x0, (pad.height if pad.collapsed else y1 - y0)
        if (w < pad.width or h < pad.height) and pad.own_size is None:
            pad.own_size = [pad.width, pad.height]
        pad.x, pad.y, pad.width, pad.height = x0, y0, w, h
        pad.stacked = how == "piled"
        self.space_changed()

    def _slide_groups(self) -> None:
        """Each link group with a member off its screens slides in as one shape (space.slide_in of its
        union), in one glide. One that cannot fit as one shape is placed member by member (return_note)
        and the members that move lose their links."""
        areas, screens = self.usable(), self.screens()
        slides, seen = {}, set()
        for pid in list(self.windows):
            group = self.group_of(pid) & set(self.windows)
            if pid in seen or len(group) < 2:
                continue
            seen |= group
            boxes = {i: _pad_box(self.windows[i].pad) for i in group}
            if all(geom.fits_one(b, areas) for b in boxes.values()):
                continue
            union = geom.union(list(boxes.values()))
            home = geom.screen_of(union, screens)
            dx, dy = space.slide_in(union, areas, home)
            if geom.fits_one(geom.shift(union, dx, dy), [areas[home]]):
                slides.update({i: geom.shift(b, dx, dy) for i, b in boxes.items()})
            else:
                for i, b in boxes.items():
                    if not geom.fits_one(b, areas):
                        self.links.drop(i)
        self._mirror_links()
        if slides:
            self.apply(slides)

    def return_note(self, nw: NoteWindow, why: str) -> None:
        """The one way a note comes back (``why``: "start", "reopen", "restore" or "screens"), in
        one plan that never pushes anything (N1):
        1. onto a screen; 2. its spot if free, else the nearest free one (find_spot); a stacked
        note keeps its spot (its stack slides in as one when off the screen);
        3. its calendar: docked on its saved side if that is clear, else the pair comes back
        together wherever it fits (#22A); undocked: at its own spot, or beside the note."""
        pad, pid = nw.pad, nw.pad.id
        if self.prefs.auto_layout and self._is_tile(pid):       # the tiles are arranged
            if pad.calendar and nw.calendar is None:
                if self.calendar_elsewhere(nw) is not None:
                    pad.calendar = False
                else:
                    nw.make_calendar("start")
            self.arrange_soon()
            return
        areas, gap, screens = self.usable(), self._gap(), self.screens()
        cal = nw.calendar
        excl = {pid, CAL} if cal is not None else {pid}
        self.space_changed()
        snap = self.space(exclude=excl)
        note = _pad_box(pad)
        home = geom.screen_of(note, screens)
        boxes: dict[str, Box] = {}
        if pad.stacked:                             # keeps its spot; its stack moves in as one
            stack, grew = {pid: note}, True
            while grew:
                grew = False
                for s in snap:
                    sb = s.parts[0] if s.kind == "pair" else s.box
                    if s.stacked and s.id not in stack and s.kind in ("note", "pair") and any(
                            geom.overlap(sb, b) for b in stack.values()):
                        stack[s.id], grew = sb, True
            ub = geom.union(list(stack.values()))
            if not geom.fits_one(ub, areas):
                dx, dy = space.slide_in(ub, areas, home)
                note = geom.shift(note, dx, dy)
                for sid in stack:
                    if sid != pid:
                        boxes[sid] = geom.shift(next(s.box for s in snap if s.id == sid), dx, dy)
        else:
            if not geom.fits_one(note, areas):
                dx, dy = space.slide_in(note, areas, home)
                note = geom.shift(note, dx, dy)
            if not geom.is_free(note, areas, [s.box for s in snap if not s.stacked], gap):
                w0, h0 = note[2] - note[0], note[3] - note[1]
                under = excl | {s.id for s in snap if s.stacked}    # (a note may lie under a pile: P5)
                spot, how = self.find_spot(w0, h0, note[:2], exclude=under)
                if how == "piled":
                    spot, how = self.find_spot(w0, h0, note[:2], exclude=excl)
                self._flag_spot(pad, how, spot, (w0, h0))
                note = spot
        boxes[pid] = note
        parts = None
        want = pad.calendar or cal is not None
        if want and cal is None and self.calendar_elsewhere(nw) is not None:
            pad.calendar = want = False             # one calendar at a time
        fresh = False
        if want:
            fresh = cal is None
            if fresh:
                cal = nw.calendar = CalendarPopup(nw)
                pad.calendar = True
            if cal.docked:
                side, view, cb, clear = cal.plan_dock(side=pad.calendar_side, note_box=note)
                if side is None:                    # G7: undocked, at a free spot
                    cal.undock_to(cb)
                    self._space_epoch += 1
                    boxes[CAL] = cb
                else:
                    cal.take_plan(side, view)
                    pair = clear
                    if not clear:                   # #22A: the pair comes back together, wherever it fits
                        un = geom.union([note, cb])
                        spot, how = self.find_spot(un[2] - un[0], un[3] - un[1], un[:2], exclude=excl)
                        if how == "piled":          # P5: no room for the pair: the calendar closes (pad.calendar and its side stay)
                            nw.close_calendar(remember=True)
                            cal, want, fresh = None, False, False
                            spot, how = self.find_spot(note[2] - note[0], note[3] - note[1], note[:2], exclude=excl)
                            self._flag_spot(pad, how, spot, (note[2] - note[0], note[3] - note[1]))
                            note = boxes[pid] = spot
                        else:
                            pair = True
                            self._flag_spot(pad, how, spot, (un[2] - un[0], un[3] - un[1]))
                            cl = tuple(cal.least) if cal.least else (cb[2] - cb[0], cb[3] - cb[1])
                            shape = space.Shape(pid, un, kind="pair", parts=(note, cb), side=side, cal_least=cl)
                            note, cb = space.split_pair(shape, spot, gap)
                    if pair:
                        parts = {pid: (note, cb)}
                        boxes[pid] = geom.union([note, cb])
            else:
                boxes[CAL] = self._undocked_return(nw, cal, note, snap, excl)
        self.space_changed()
        self.apply_plan(boxes, parts=parts)
        if pad.stacked and not pad.pinned:
            nw.win.lift()
        if fresh:
            cal.reveal()
            self.space_changed()
            self.calendar_buttons()
        self.request_save()

    def _flag_spot(self, pad: Pad, how: str, spot: Box, asked: tuple) -> None:
        """What find_spot's result means for a pad: piled makes it stacked; a smaller box than
        asked keeps the own size from before (P6)."""
        pad.stacked = how == "piled"
        if (spot[2] - spot[0] < asked[0] or spot[3] - spot[1] < asked[1]) and pad.own_size is None:
            pad.own_size = [pad.width, pad.height]

    def _undocked_return(self, nw: NoteWindow, cal, note: Box, snap: list, excl) -> Box:
        """Where an undocked calendar comes back (N1): its saved spot, at its own size, when that
        is free and a gap from the note; else the nearest free spot."""
        pad, gap, areas = nw.pad, self._gap(), self.usable()
        if cal.target_box is not None:
            w, h = cal.target_box[2] - cal.target_box[0], cal.target_box[3] - cal.target_box[1]
        else:
            cal.fit_size = None
            cal.top.geometry("")
            w, h = cal._size()
        pos = pad.calendar_pos or pad.calendar_big_pos
        if pos is None:
            boxes = [calgeom.spot_box(note, s, w, h, gap) for s in calgeom.SIDES]
            fit = next((b for b in boxes if geom.fits_one(b, areas)), None)
            if fit is None:
                r, a = boxes[0], self.area_of(boxes[0])
                fit = (min(max(r[0], a[0]), max(a[0], a[2] - w)), min(max(r[1], a[1]), max(a[1], a[3] - h)))
            pos = list(fit[:2])
        pad.calendar_pos = [int(pos[0]), int(pos[1])]
        x, y = pad.calendar_pos
        cb = (x, y, x + w, y + h)
        obstacles = [s.box for s in snap]
        if not geom.is_free(cb, [self.area_of(cb)], obstacles + [note], gap):
            cb, _how = self.find_spot(w, h, (x, y), exclude=excl, avoid=(note,))
            pad.calendar_pos = list(cb[:2])
        return cb

    def detach(self, nw: NoteWindow):
        """Menu "Detach this note": it moves the shortest way to where it touches nothing (every
        other box a gap and 1 px away), as one glide with no Undo; only it moves, and its links go."""
        pid = nw.pad.id
        if len(self.group_of(pid)) < 2:
            return False
        slack, reach = self._touch_reach()
        shape = self.shape_of(nw)                   # (with its docked calendar: the pair moves as one)
        here = shape.box
        w, h = here[2] - here[0], here[3] - here[1]
        areas, screens = self.usable(), self.screens()
        obstacles = [s.box for s in self.space(exclude={pid, CAL} if shape.kind == "pair" else {pid})]
        home = geom.screen_of(here, screens)
        spot = space.nearest_free(w, h, here[:2], areas, obstacles, reach + 1, home)
        self.unlink(pid)                            # (M2: Detach breaks its links, wherever it ends up)
        if spot is None:                            # a crowded screen: the usual last resort
            spot, how = self.find_spot(w, h, here[:2], exclude={pid, CAL} if shape.kind == "pair" else {pid})
            self._flag_spot(nw.pad, how, spot, (w, h))
        self.apply_plan({pid: spot})
        return True

    def grow(self, changes: dict, mode: str, undo_label: str | None = None, *, by_calendar: bool = False,
             parts: dict | None = None, shapes: list | None = None, before: dict | None = None,
             offer: bool = False) -> dict:
        """Make room for ``changes`` (id -> new box) as one plan (space.plan_growth against
        space()) and apply it. ``parts``: an owner's exact new (note, calendar) boxes. Returns the
        boxes the growers may have (drag mode: clamped at the edge), {} in app mode. ``shapes``: the
        space list to plan against (a resize planned from the boxes at its start, a fold from before
        it); ``before``: the layout Undo goes back to (a live resize moved the pads already);
        ``offer``: the Undo is offered even when only the growers moved."""
        parts = parts or {}
        changes = {k: tuple(int(v) for v in b) for k, b in changes.items()}
        cal = self._open_calendar()
        shapes = list(shapes) if shapes is not None else self.space()
        if parts and CAL not in changes:            # docking: the undocked calendar becomes part of the owner's pair
            shapes = [s for s in shapes if s.id != CAL]
        if self.prefs.auto_layout:                  # the tiles decide (arrange): a calendar being opened gets its box
            if cal is not None and cal.target_box is None:
                box = next((p[1] for p in parts.values()), changes.get(CAL))
                if box is not None:
                    cal.move_to(box)
            self.arrange()
            return {}
        screens, gap, px = self.screens(), self._gap(), self.px
        areas = geom.usable(screens, gap)
        cal_box = next((p[1] for p in parts.values()), changes.get(CAL))
        if cal_box is None and cal is not None and _placed(cal):
            cal_box = tuple(cal.target_box)
        area = areas[geom.screen_of(geom.union(list(changes.values())), screens)]
        plan = space.plan_growth(changes, shapes, self.links, areas, gap, mode=mode, min_w=px(MIN_W), min_h=px(MIN_H),
                                 pile_corner_=space.pile_corner(area, cal_box), step=px(PILE_STEP), slack=px(2))
        boxes = dict(plan.boxes)
        for g, b in changes.items():
            boxes.setdefault(g, b)
        moved_parts = dict(parts)
        for g, (nb, cb) in parts.items():           # drag mode, clamped: only the part that grew is cut back
            fb, nw = boxes.get(g), self.windows.get(g)
            if fb is None or fb == changes[g] or nw is None:
                continue
            old_note = geom.pad_box(nw.pad)
            old_cal = tuple(cal.target_box) if cal is not None and cal.target_box is not None else None

            def clip(b, old):
                if old is not None and tuple(b) == tuple(old):
                    return b
                return max(b[0], fb[0]), max(b[1], fb[1]), min(b[2], fb[2]), min(b[3], fb[3])
            moved_parts[g] = (clip(nb, old_note), clip(cb, old_cal))
        for pid in plan.piled:
            if pid in self.windows:
                self.windows[pid].pad.stacked = True
        for pid in plan.shrunk:
            nw = self.windows.get(pid)
            if nw is not None and nw.pad.own_size is None:
                nw.pad.own_size = [nw.pad.width, nw.pad.height]
        others = [i for i in plan.boxes if i not in changes]
        if by_calendar:                             # P4: what the calendar moved goes home when it gives room back
            for pid in set(others) | set(plan.piled) | set(plan.shrunk):
                nw = self.windows.get(pid)
                if nw is not None and pid not in changes and nw.pad.cal_mark is None:
                    x0, y0, x1, y1 = geom.pad_box(nw.pad)
                    nw.pad.cal_mark = [x0, y0, x1 - x0, y1 - y0]
        self.apply_plan(boxes, parts=moved_parts, undo_label=undo_label if others or offer else None,
                        before=before)
        for pid in plan.piled:                      # a pile is drawn above what it lies over (every top bar shows)
            if pid in self.windows and not self.windows[pid].pad.pinned:
                self.windows[pid].win.lift()
        return dict(plan.allowed)

    def plan_resize(self, changes: dict, shapes: list):
        """The plan of a live resize (drag mode, against ``shapes``): nothing is applied."""
        screens, gap, px = self.screens(), self._gap(), self.px
        areas = geom.usable(screens, gap)
        cal = self._open_calendar()
        cal_box = tuple(cal.target_box) if cal is not None and _placed(cal) else None
        area = areas[geom.screen_of(geom.union(list(changes.values())), screens)]
        return space.plan_growth(changes, shapes, self.links, areas, gap, mode="drag", min_w=px(MIN_W),
                                 min_h=px(MIN_H), pile_corner_=space.pile_corner(area, cal_box),
                                 step=px(PILE_STEP), slack=px(2))

    def close_up(self, changes: dict, shapes: list | None = None) -> None:
        """P4: ``changes`` (id -> a smaller box: a fold) close up with whatever is linked in line.
        One plan against ``shapes`` (default space()), applied once; no Undo."""
        changes = {k: tuple(int(v) for v in b) for k, b in changes.items()}
        shapes = list(shapes) if shapes is not None else self.space()
        plan = space.plan_close_up(changes, shapes, self.links, self._gap(), areas=self.usable(), slack=self.px(2))
        self.apply_plan(plan.boxes)

    def outlines(self):
        """The one dashed-outline window of the live drags (made when first needed)."""
        if getattr(self, "_outlines", None) is None:
            self._outlines = Outlines(self)
        return self._outlines

    def give_back(self, toward: Box) -> None:
        """P4: the calendar closed or shrank (``toward``: its new box, or its last one when it
        closed): the notes it moved go back to their own boxes where free, else close up toward it.
        Every id moved is unstacked; those home lose their mark."""
        marks = {}
        for pid, nw in self.windows.items():
            m = nw.pad.cal_mark
            if m is not None and not nw._closing:
                marks[pid] = (m[0], m[1], m[0] + m[2], m[1] + m[3])
        if not marks or self.prefs.auto_layout:
            return
        self.space_changed()
        shapes = self.space()
        plan = space.plan_give_back(marks, shapes, self.links, self.usable(), self._gap(),
                                    tuple(toward) if toward is not None else None)
        now = {s.id: s.box for s in shapes}
        for pid in plan.boxes:
            nw = self.windows.get(pid)
            if nw is not None:
                nw.pad.stacked = False
        for pid, m in marks.items():
            if plan.boxes.get(pid, now.get(pid)) == m:
                self.windows[pid].pad.cal_mark = None
        if plan.boxes:
            self.apply_plan(dict(plan.boxes), undo_label=None)
        self.request_save()

    def bring_back(self, nw: NoteWindow, places: dict):
        """Kept for the callers that name the dragged window and where each member was put:
        settle_drop of those notes (``places``: window -> (x, y))."""
        return self.settle_drop({w.pad.id for w in places}, places=places, anchor=nw)

    def settle_drop(self, ids: set, places: dict | None = None, anchor=None) -> dict:
        """After a drag or a resize (M1, M3): the dropped ``ids`` (note ids, and CAL for the
        undocked calendar) end up on the screen and clear of everything else, in one plan.
        1. Only when a member (a note with its docked calendar, or the calendar) doesn't fit one
           usable area, the whole group slides back in as one (space.slide_in of the union).
        2. Still too close to something (or sitting on it): the group goes to the nearest free
           spot (M1), keeping its shape.
        3. Members that still don't fit (a group wider than the screen, a crowded screen) go one
           by one to find_spot (P5): shrunk, or on the overflow pile.
        Then everything glides there in one apply (a note already gliding goes on from where it
        is now: its pad is not written to). ``places``: window -> (x, y) where the drag put it
        (default: where the pads say); ``anchor``: the window whose screen counts."""
        areas, gap, screens = self.usable(), self._gap(), self.screens()
        cal = self._open_calendar()
        if places is None:
            places = {w: geom.pad_box(w.pad)[:2] for i, w in self.windows.items()
                      if i in ids and not w._closing and w.win.state() == "normal"}
        free_cal = cal is not None and CAL in ids and not cal.docked and cal.target_box is not None
        w_of = {w.pad.id: w for w in places}

        def box(w, xy):
            return xy[0], xy[1], xy[0] + w.pad.width, xy[1] + _shown_h(w.pad)

        def shape(w, xy):       # with its docked calendar where it will follow it (C1): one shape (S1, M3)
            b = box(w, xy)
            if cal is None or cal.nw is not w or not cal.docked or cal.target_box is None:
                return b
            return geom.union([b, Motion._follow(cal, _pad_box(w.pad), b)])
        own = {w.pad.id: box(w, xy) for w, xy in places.items()}        # what moves: the note, or CAL
        shapes_ = {w.pad.id: shape(w, xy) for w, xy in places.items()}  # what must fit: with its calendar
        if free_cal:
            own[CAL] = shapes_[CAL] = tuple(cal.target_box)
        if not own:
            return {}
        self.space_changed()
        others = self.space(set(own))
        obstacles = [b for s in others for b in (s.parts or (s.box,))]
        union = geom.union(list(shapes_.values()))
        here = box(anchor, places[anchor]) if anchor in places else union
        home = geom.screen_of(here, screens)
        dx = dy = 0
        slid = not all(geom.fits_one(b, areas) for b in shapes_.values())
        if slid:
            dx, dy = space.slide_in(union, areas, home)

        def moved(b, ox, oy):
            return b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy
        own = {k: moved(b, dx, dy) for k, b in own.items()}
        shapes_ = {k: moved(b, dx, dy) for k, b in shapes_.items()}
        fits = (lambda b: geom.fits_one(b, [areas[home]])) if slid else (lambda b: geom.fits_one(b, areas))
        outside = [k for k in own if k != CAL and not fits(own[k])]
        inside = [k for k in own if k not in outside]
        if inside:
            ub = geom.union([shapes_[k] for k in inside])
            parts = [shapes_[k] for k in inside]
            if len(parts) > 1:              # a group: each of its pieces counts, not the empty corners
                crowded = [b for b in parts if not geom.is_free(b, areas, obstacles, gap)]   # between them (E)
                # only shown notes in the way: they make room (push_clear), the group stays
                blocked = any(s.kind != "note" for b in crowded for s in others
                              for q in (s.parts or (s.box,)) if geom.overlap(b, geom.inflate(q, gap - 1)))
                blocked = blocked or any(not geom.fits_one(b, areas) for b in crowded)
            else:
                blocked = not geom.is_free(ub, areas, obstacles, gap)
            if blocked:                     # too close to (or on) something: M1
                spot = space.nearest_free(ub[2] - ub[0], ub[3] - ub[1], ub[:2], areas, obstacles, gap, home)
                if spot is not None:
                    ox, oy = spot[0] - ub[0], spot[1] - ub[1]
                    own.update({k: moved(own[k], ox, oy) for k in inside})
                    shapes_.update({k: moved(shapes_[k], ox, oy) for k in inside})
                else:
                    outside += [k for k in inside if k != CAL]
                    inside = [k for k in inside if k == CAL]
        if not outside and not slid and all(own[k] == (box(w_of[k], places[w_of[k]]) if k != CAL
                                                       else tuple(cal.target_box)) for k in own):
            return {}
        saved = {w: (w.pad.x, w.pad.y, w.pad.width, w.pad.height, getattr(w.pad, "target", None)) for w in places}
        sizes = {w: (w.pad.width, w.pad.height) for w in places}
        driven = {w for w in places if self.motion.drives(w.pad.id)}   # gliding: it goes on from where it is
        cal_was = tuple(cal.target_box) if free_cal else None
        for k in inside:                            # the ones inside first: space() sees them there
            if k == CAL:
                cal.target_box = own[CAL]
            else:
                w_of[k].pad.target = own[k][:2]
        self.space_changed()
        for i, k in enumerate(outside):             # each in turn, clear of those placed before it
            w = w_of[k]
            p, xy = w.pad, own[k][:2]
            left, top, right, bottom = areas[home]
            origin = (min(max(xy[0], left), right - p.width), min(max(xy[1], top), bottom - _shown_h(p)))
            spot, how = self.find_spot(p.width, _shown_h(p), origin, exclude=set(outside[i:]))
            self.take_spot(p, spot, how)            # (shrunk to fit: the spot's size; flags only matter here)
            p.target = spot[:2]
            own[k] = (spot[0], spot[1], spot[0] + p.width, spot[1] + _shown_h(p))
        goal = {k: b for k, b in own.items()}
        if free_cal:
            cal.target_box = cal_was
        for w, xy in places.items():                # the pads where the windows are: Motion goes from there
            p = w.pad
            if w in driven:                         # (a gliding pad holds its old spot: starts would jump it back)
                p.x, p.y, p.width, p.height, p.target = saved[w]
                continue
            p.x, p.y = xy
            p.width, p.height = sizes[w]
            p.target = None
        self.space_changed()
        self.apply(goal, starts={w.pad.id: xy for w, xy in places.items() if w not in driven})
        return goal

    # ---- applying a plan: every move goes through motion (S4) ---------------------------------
    def apply(self, targets: dict[str, Box], *, undo_label: str | None = None, ms: int | None = None,
              done=None, anchor=None, starts: dict | None = None, before: dict | None = None) -> None:
        """Glide every window in ``targets`` to its box, once, on the one clock (Motion.run).
        Window level: a pad id means that note's own box, CAL the calendar's. ``undo_label``
        (a texts key): Undo is offered once the action ends (offer_undo), on ``anchor`` (a
        NoteWindow), else on the first pad id's note. Plans that supersede a running one are one
        action: the first plan's boxes stay as the ``before`` (ids only a later plan touches
        join with their own), and the one offer at the final end carries the last plan's label.
        Any apply ends the Undo on offer (but the restore's own). ``starts``: where windows start
        that are not where their pads say (Motion.run)."""
        targets = dict(targets)
        if not self._restoring:
            self._drop_undo()
        chain = self._chain if self.motion.busy() else None
        fresh = self.layout_of(list(targets))
        if chain is None:
            chain = self._chain = {"before": fresh, "gen": 0}
        else:
            for pid, b in fresh.items():        # (ids the chain already moves keep their first box)
                chain["before"].setdefault(pid, b)
        chain["gen"] += 1
        chain.update(label=undo_label, anchor=anchor, first=next(iter(targets), None))
        if before:                              # a live resize: the boxes from before it started
            chain["before"].update(before)
        gen = chain["gen"]

        def finished():
            if self._chain is chain and chain["gen"] == gen:    # the last plan's end only
                self._chain = None
                before, label = chain["before"], chain["label"]
                if label is not None and self.layout_of(list(before)) != before:
                    nw = chain["anchor"] or self.windows.get(chain["first"]) or next(
                        (self.windows[i] for i in before if i in self.windows), None)
                    self.offer_undo(before, label, nw)
            if done is not None:
                done()
        self.motion.run(targets, ms=ms, done=finished, starts=starts)

    def apply_plan(self, boxes: dict[str, Box], *, parts: dict | None = None, **kw) -> None:
        """apply() for a planner's output, keyed by shape id (space()). An id in ``parts`` is
        its (note, calendar) boxes as given, whatever its shape now (the calendar opening or
        docking makes a plain note a pair); any other pair is split by space.split_pair."""
        parts = parts or {}
        shapes = {s.id: s for s in self.space()}
        targets: dict[str, Box] = {}
        for sid, b in boxes.items():
            if sid in parts:
                targets[sid], targets[CAL] = parts[sid]
            elif sid in shapes and shapes[sid].kind == "pair":
                targets[sid], targets[CAL] = space.split_pair(shapes[sid], b, self._gap())
            else:
                targets[sid] = b
        self.apply(targets, **kw)

    def offer_undo(self, before, label, anchor_nw) -> None:
        """Offer one Undo for an action that moved things (S5): ``label`` (a texts key) on
        ``anchor_nw``'s toast with the Undo button, which puts ``before`` back (restore_layout).
        One at a time; it goes after UNDO_MS or with the next apply of any kind."""
        self._drop_undo()
        if anchor_nw is None or not anchor_nw.win.winfo_exists():
            anchor_nw = next((self.windows[i] for i in before if i in self.windows), None)
        if anchor_nw is None:
            return
        offer = self._undo = {"before": dict(before), "anchor": anchor_nw.pad.id, "action": self.undo_now}
        offer["job"] = self.root.after(UNDO_MS, lambda: self._undo is offer and self._drop_undo())
        anchor_nw.show_undo_action(tr(label), self.undo_now)

    def _drop_undo(self) -> None:
        """The Undo on offer ends: its toast goes (if still showing it) and it can't be run."""
        offer, self._undo = self._undo, None
        if offer is None:
            return
        self.root.after_cancel(offer["job"])
        nw = self.windows.get(offer["anchor"])
        if nw is not None and nw._undo_action == offer["action"] and nw.win.winfo_exists():
            nw.hide_undo()

    def undo_now(self) -> None:
        """Run the Undo on offer, if any (the toast's button): every window back where it was."""
        offer = self._undo
        if offer is None:
            return
        self._drop_undo()
        self.restore_layout(offer["before"])

    def layout_of(self, ids) -> dict[str, Box]:
        """Where each id's window is (going), for Undo: a note's box (its pad box), and CAL's
        target_box when CAL is asked for or is docked to one of these notes (it moves with them)."""
        ids, out = list(ids), {}
        for pid in ids:
            nw = self.windows.get(pid)
            if pid != CAL and nw is not None:
                out[pid] = _pad_box(nw.pad)
        cal = self._open_calendar()
        if cal is not None and _placed(cal) and (CAL in ids or (cal.docked and cal.nw.pad.id in out)):
            out[CAL] = tuple(cal.target_box)
        return out

    def restore_layout(self, layout: dict[str, Box]) -> None:
        """Undo a tidy or a group resize: every id back to its box, in one apply (one glide)."""
        targets = {}
        for pid, b in layout.items():
            if pid == CAL:
                cal = self._open_calendar()
                if cal is not None and not getattr(cal, "_closing", False):
                    targets[CAL] = b
            elif pid in self.windows and not self.windows[pid]._closing and self.windows[pid].win.winfo_exists():
                targets[pid] = b
        self._restoring = True
        try:
            self.apply(targets)
        finally:
            self._restoring = False

    def fold_all(self, on: bool):
        """Menu "Fold up all notes" / "Unfold all notes": every shown note changes in one plan
        (S4), so each note moves once. No Undo (restore_layout does not put back the fold)."""
        wins = [w for w in self.windows.values() if w.win.state() == "normal" and not w._closing
                and w.pad.collapsed != on]
        if self.prefs.auto_layout:
            for w in wins:
                w.pad.collapsed = on
                w._apply_collapsed(shoot=True)
            self.arrange()
        else:
            self.set_folded(wins, on)
        self.request_save()

    def set_folded(self, wins: list, on: bool) -> None:
        """Fold (``on``) or unfold ``wins`` as one plan: folding closes up with every link (P4:
        whatever is in line and linked, whatever Alt or the drag switch say), unfolding pushes
        like any growth in app mode (nothing is dragged: F36). Both plan against the space list
        from before, as the notes already show their new state. No Undo."""
        if not wins:
            return
        old = self.space()
        by_id = {s.id: s for s in old}
        for w in wins:
            w.pad.collapsed = on
            w._apply_collapsed(shoot=True)
        changes, parts = {}, {}
        for w in wins:
            note, s = _pad_box(w.pad), by_id.get(w.pad.id)
            if s is not None and s.kind == "pair":
                parts[w.pad.id] = (note, s.parts[1])
                note = geom.union([note, s.parts[1]])
            changes[w.pad.id] = note
        if on:
            self.close_up(changes, old)
        else:
            self.grow(changes, "app", shapes=old, parts=parts)
