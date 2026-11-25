"""Run this preview beside the installed Sticky Note, on its own notes folder.

It uses the "preview-data" folder next to this file, never %APPDATA%\\StickyNote,
has its own taskbar group and takes no single-instance lock.
"""
import sys
from pathlib import Path

import winapi

HERE = Path(__file__).resolve().parent
folder = HERE / "preview-data"
folder.mkdir(exist_ok=True)
winapi.set_dpi_aware()
winapi.set_app_id("KMH.StickyNote.Preview")
from app import App
App(folder).root.mainloop()
