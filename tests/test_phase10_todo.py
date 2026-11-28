"""Phase 10, task 4 (2026-11-28): a to-do settles both ways. Ticking fades the line to the done
grey (phase 8); unticking now fades it back to the ink instead of snapping."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from ui_common import DONE_FADE_MS


class TodoSettleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = nw = next(iter(self.app.windows.values()))
        nw.body.focus_force()
        nw.body.insert("1.0", "우유 사기")
        nw.toggle_todo()
        self.settle()

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.2):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def fade_fg(self):
        b = self.nw.body
        return str(b.tag_cget("done_fade", "foreground")) if b.tag_ranges("done_fade") else None

    def test_untick_fades_back(self):
        nw, c = self.nw, self.nw.colors
        nw.set_done(1, True)
        self.settle()
        nw.set_done(1, False)
        pump(self.app, timeout=DONE_FADE_MS / 2000)
        mid = self.fade_fg()
        self.assertIsNotNone(mid)
        self.assertNotIn(mid.upper(), (str(c.fg).upper(), str(c.muted).upper()))   # on its way
        self.settle()
        self.assertIsNone(self.fade_fg())                      # done: the line's own ink again

    def test_off_snaps(self):
        self.app.set_motion("off")
        nw = self.nw
        nw.set_done(1, True)
        nw.set_done(1, False)
        shown = self.fade_fg()                                 # at once: the ink (no in-between)
        self.assertIn(shown, (None, str(nw.colors.fg)))
        self.settle()
        self.assertIsNone(self.fade_fg())


if __name__ == "__main__":
    unittest.main()
