import pathlib
import re
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
import anim
from ui_common import _alpha, fade


class WrapperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        pump(self.app, timeout=0.5)
        self.nw = next(iter(self.app.windows.values()))

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def test_app_has_clock(self):
        self.assertIs(anim.clock_of(self.app.root), self.app.clock)

    def test_fades_share_one_alpha_owner(self):
        w = self.nw.win
        fade(w, "a", 1.0, 0.2, 240)
        pump(self.app, timeout=0.08)
        mid = _alpha(w)
        fade(w, "b", 0.2, 1.0, 240)                 # a different key: still the same owner
        self.assertAlmostEqual(_alpha(w), mid, delta=0.05)   # no jump to 0.2 when it starts
        pump(self.app, timeout=0.4)
        self.assertAlmostEqual(_alpha(w), 1.0, places=2)

    def test_minimize_restore_round_trip(self):
        self.app.prefs.minimize_style = "fold"            # (the default "bar" folds instead of minimizing)
        p = self.nw.pad
        box = (p.x, p.y, p.width, p.height)
        self.nw.minimize()
        pump(self.app, timeout=1.0)
        self.nw.restore()
        pump(self.app, timeout=1.0)
        self.assertEqual((p.x, p.y, p.width, p.height), box)
        self.assertEqual(self.nw.win.state(), "normal")
        self.assertFalse(self.nw.rolling)

    def test_quit_closes_clock(self):
        clock = self.app.clock
        close_app(self.app)
        self.assertFalse(clock.busy)
        self.assertIsNone(clock._job)

    @unittest.expectedFailure                       # until Tasks 6-7 move motion.py and the fly loop
    def test_no_frame_loops_outside_anim(self):
        app_dir = pathlib.Path(anim.__file__).parent
        for f in app_dir.glob("*.py"):
            if f.name == "anim.py":
                continue
            src = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\.after\(\s*FRAME_MS", src), f.name)
            self.assertNotIn("_keep_timer_fine", src, f.name)


if __name__ == "__main__":
    unittest.main()
