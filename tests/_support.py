"""Shared test helpers: a real App on a temp folder with one fake screen.

Run the suite with the bundled runtime from the project root:
    .\\StickyNote\\runtime\\python.exe -m unittest discover -s tests -v
"""
import time
import tkinter as tk
from pathlib import Path
from typing import Callable

import winapi

winapi.set_dpi_aware()

from app import App  # noqa: E402  (after DPI setup, like main.py)
from geom import Screen  # noqa: E402

SCREEN = Screen(monitor=(0, 0, 1920, 1080), work=(0, 0, 1920, 1040))


def make_app(folder: Path) -> App:
    return App(folder, screens=[SCREEN])


def pump(app: App, until: Callable[[], bool] = lambda: False, timeout: float = 2.0) -> bool:
    """Run Tk's event loop until ``until()`` is true (True) or ``timeout`` seconds pass (False)."""
    end = time.perf_counter() + timeout
    while True:
        try:
            if until():
                return True
        except tk.TclError:
            return False
        if time.perf_counter() >= end:
            return False
        try:
            app.root.update()
        except tk.TclError:                     # the root is gone (the app quit)
            try:
                return bool(until())
            except tk.TclError:
                return False
        time.sleep(0.01)


def close_app(app: App) -> None:
    if not app.closed:
        try:
            app.quit()
        except tk.TclError:
            pass
