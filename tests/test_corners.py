"""Phase 3, Task 1: Windows 11 rounded corners (DWM) or the 1 px border fallback."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import winapi
from _support import close_app, make_app, patched, pump


class CornersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        pump(self.app, timeout=0.3)
        self.nw = next(iter(self.app.windows.values()))

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def test_round_corners_on_mapped_window(self):
        top = tk.Toplevel(self.app.root)
        top.overrideredirect(True)
        top.geometry("120x80+50+50")
        pump(self.app, timeout=0.1)
        self.assertEqual(winapi.round_corners(top), winapi.can_round())
        top.destroy()
        later = tk.Toplevel(self.app.root)
        later.withdraw()                                # never shown: no frame window yet
        self.assertFalse(winapi.round_corners(later))
        later.destroy()

    def test_note_edge_follows_corners(self):
        if winapi.can_round():
            self.assertEqual(self.nw.edge, 0)
            self.assertEqual(int(self.nw.frame.pack_info()["padx"]), 0)
        with patched(winapi, "round_corners", lambda win: False):
            nw = self.app.new_window(self.nw)
            pump(self.app, timeout=0.4)
        self.assertEqual(nw.edge, 1)
        self.assertEqual(int(nw.frame.pack_info()["padx"]), 1)
        self.assertEqual(nw.win.cget("bg"), nw.colors.frame)

    def test_calendar_edge_follows_corners(self):
        self.nw.toggle_calendar()
        pump(self.app, lambda: not self.app.motion.busy(), timeout=1)
        pump(self.app, timeout=0.3)
        cal = self.nw.calendar
        if winapi.can_round():
            self.assertEqual(cal.edge, 0)
            self.assertEqual(int(cal.frame.pack_info()["padx"]), 0)
        self.nw.toggle_calendar()
        pump(self.app, timeout=0.4)
        with patched(winapi, "round_corners", lambda win: False):
            self.nw.toggle_calendar()
            pump(self.app, lambda: not self.app.motion.busy(), timeout=1)
            pump(self.app, timeout=0.3)
        cal = self.nw.calendar
        self.assertEqual(cal.edge, 1)
        self.assertEqual(int(cal.frame.pack_info()["padx"]), 1)


if __name__ == "__main__":
    unittest.main()
