"""Names the app's modules share (constants and small helpers that were app.py's own)."""
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

def _placed(cal) -> bool:
    """The calendar takes up space: it has been placed (target_box) and is not closing."""
    return getattr(cal, "target_box", None) is not None and not getattr(cal, "_closing", False)


def _side_of(note: Box, cal: Box) -> str:
    """Which side of the note's box the docked calendar's box is on: by their facing edges,
    else (overlapping, kept on a crowded screen) by their centres."""
    if cal[0] >= note[2]:
        return "right"
    if cal[2] <= note[0]:
        return "left"
    if cal[1] >= note[3]:
        return "below"
    if cal[3] <= note[1]:
        return "above"
    (nx, ny), (cx, cy) = geom.center(note), geom.center(cal)
    if abs(cx - nx) >= abs(cy - ny):
        return "right" if cx >= nx else "left"
    return "below" if cy >= ny else "above"


QUIT_SIGNAL = "quit.signal"             # the installer asks a running app to close (saved)

SETUPS_KEPT = 8                  # monitor setups whose note places are remembered (the ones seen last)
GRID_HOMES_KEPT = 16             # ... and auto layout homes (one per screen of those setups)
CLOSED_KEPT = 20                 # closed notes "Reopen closed note" can bring back
PICTURE_BUDGET = 64 * 1024 * 1024   # bytes of shrunk pictures kept for the list, the strip and the preview


def _keep_recent(d: dict, key, value, limit=SETUPS_KEPT) -> None:
    """``d[key] = value``, ``key`` now the most recent; only the ``limit`` most recent are kept
    (a dict keeps its order, in memory and in the saved file)."""
    d.pop(key, None)
    d[key] = value
    for old in list(d)[:-limit]:
        del d[old]


__all__ = [_n for _n in list(globals()) if not _n.startswith("__")]
