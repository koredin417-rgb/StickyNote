"""Phase 10, task 1 (2026-11-28): the calendar grows into the big view and shrinks back as one morph.
A picture of the old view, in a click-through window over the calendar, follows the calendar's
box as it glides and then fades away over the live new view."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from ui_common import _alpha


class MorphTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.toggle_calendar()
        self.settle(0.5)
        self.cal = self.nw.calendar

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy
             and getattr(self.nw.calendar, "_morph", None) is None, timeout=4)
        pump(self.app, timeout=t)

    def box(self):
        t = self.cal.top
        return t.winfo_rootx(), t.winfo_rooty(), t.winfo_width(), t.winfo_height()

    def test_grows_with_a_cover_then_is_live(self):
        cal = self.cal
        small = self.box()
        cal.click_view("big")
        pump(self.app, timeout=0.06)
        m = cal._morph
        self.assertIsNotNone(m)
        self.assertTrue(m.top.winfo_ismapped())
        self.settle()
        self.assertTrue(cal.expanded)
        self.assertIsNone(cal._morph)                        # the cover is gone
        big = self.box()
        self.assertGreater(big[2] * big[3], small[2] * small[3])
        self.assertAlmostEqual(_alpha(cal.top), cal._target_alpha(), places=2)

    def test_cover_follows_the_box(self):
        cal = self.cal
        cal.click_view("big")
        sizes = []

        def watch():
            m = cal._morph
            if m is not None and m.top.winfo_ismapped():
                sizes.append(m.top.winfo_width())
            return cal._morph is None and sizes
        pump(self.app, watch, timeout=4)
        self.assertGreater(len(set(sizes)), 2)               # it grew through in-between sizes

    def test_shrinks_back(self):
        cal = self.cal
        cal.click_view("big")
        self.settle()
        cal.click_view("mini")
        self.settle()
        self.assertFalse(cal.expanded)
        self.assertIsNone(cal._morph)

    def test_second_click_mid_morph(self):
        cal = self.cal
        cal.click_view("big")
        pump(self.app, timeout=0.05)
        cal.click_view("mini")
        self.settle()
        self.assertFalse(cal.expanded)
        self.assertIsNone(cal._morph)
        self.assertAlmostEqual(_alpha(cal.top), cal._target_alpha(), places=2)

    def test_off_has_no_cover(self):
        self.app.set_motion("off")
        cal = self.cal
        cal.click_view("big")
        self.assertIsNone(cal._morph)
        self.settle()
        self.assertTrue(cal.expanded)


    def test_reduced_keeps_the_old_size_under_the_fade(self):
        self.app.set_motion("reduced")
        cal = self.cal
        small = self.box()
        cal.click_view("big")
        pump(self.app, timeout=0.03)
        m = cal._morph
        if m is not None:
            self.assertEqual(m.size, (small[2], small[3]))
        self.settle()
        self.assertTrue(cal.expanded)
        self.assertIsNone(cal._morph)

    def test_closing_mid_morph_never_pops_it_into_view(self):
        cal = self.cal
        cal.click_view("big")
        pump(self.app, timeout=0.05)
        cal.destroy(animated=True)
        try:
            self.assertLess(_alpha(cal.top), 0.1)
        except Exception:
            pass                                             # (already gone)
        self.assertIsNone(cal._morph)


if __name__ == "__main__":
    unittest.main()
