"""The taskbar's "Close window" on the app's one button (the proxy) closes the app.

Without its own WM_DELETE_WINDOW, Tk destroyed the proxy; Windows took the notes it owns
with it, and the app ran on with nothing on screen, holding the single-instance lock: every
later start only pinged a "show" that had nothing left to show (2026-11-28)."""
import ctypes
import json
import tempfile
import unittest
from pathlib import Path

import winapi
from _support import close_app, make_app, pump
from store import Note

WM_SYSCOMMAND, SC_CLOSE = 0x0112, 0xF060


class ProxyCloseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.app = make_app(self.folder)
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.body.insert("1.0", "keep me")              # (typed: a note with something in it)
        self.nw.sync_from_widgets()
        pump(self.app, lambda: not self.app.motion.busy(), timeout=2)
        pump(self.app, timeout=0.3)

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def close_from_taskbar(self):
        frame = int(self.app.proxy.wm_frame(), 16)          # (the button's window: the proxy's frame)
        ctypes.windll.user32.PostMessageW(frame, WM_SYSCOMMAND, SC_CLOSE, 0)
        pump(self.app, lambda: self.app.closed, timeout=3)

    def test_close_window_quits_the_app(self):
        self.close_from_taskbar()
        self.assertTrue(self.app.closed)                    # (not running on with no windows)

    def test_close_window_keeps_the_notes(self):
        self.close_from_taskbar()
        saved = json.loads((self.folder / "notes.json").read_text(encoding="utf-8"))
        self.assertIn(self.nw.note.id, [p["note_id"] for p in saved["pads"]])     # back at the next start
        self.assertIn("keep me", [n["body"] for n in saved["notes"]])


if __name__ == "__main__":
    unittest.main()
