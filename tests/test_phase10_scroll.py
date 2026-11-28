"""Phase 10, task 7 (2026-11-28, the user's idea): scrolling. The thumb shows when the pointer nears
the right edge and eases wider under it; a wheel notch glides; the list, Settings and the bin
bounce a little at their ends (never the memo text)."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from ui_common import SCROLL_BOUNCE, SCROLL_SMOOTH_MS, SCROLL_W, SCROLL_W_HOVER, animating


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.settle()

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.2):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def settings_area(self):
        self.nw.show_settings()
        self.settle()
        return self.nw.settings_view.list_area

    def wheel(self, widget, delta):
        widget.event_generate("<MouseWheel>", delta=delta, x=10, y=10)


class PageScrollTest(Case):
    def test_notch_glides(self):
        area = self.settings_area()
        c = area.canvas
        start = c.canvasy(0)
        self.wheel(c, -120)
        pump(self.app, timeout=SCROLL_SMOOTH_MS / 3000)
        mid = c.canvasy(0)
        self.settle()
        end = c.canvasy(0)
        self.assertGreater(end, start)
        self.assertTrue(start < mid < end, (start, mid, end))

    def test_bounce_at_the_top(self):
        area = self.settings_area()
        c = area.canvas
        self.assertEqual(c.canvasy(0), 0)
        self.wheel(c, 120)                      # up, already at the top
        pump(self.app, timeout=0.04)
        y = c.coords(area._item)[1]
        self.assertGreater(y, 0)
        self.assertLessEqual(y, self.app.px(SCROLL_BOUNCE))
        self.settle(0.3)
        self.assertEqual(c.coords(area._item)[1], 0)
        self.assertEqual(c.canvasy(0), 0)

    def test_reduced_jumps_without_bounce(self):
        self.app.set_motion("reduced")
        area = self.settings_area()
        c = area.canvas
        self.wheel(c, 120)
        pump(self.app, timeout=0.02)
        self.assertEqual(c.coords(area._item)[1], 0)
        self.wheel(c, -120)
        pump(self.app, timeout=0.02)
        moved = c.canvasy(0)
        self.settle()
        self.assertEqual(c.canvasy(0), moved)   # (no in-between: it was there at once)


class ThumbTest(Case):
    def test_shows_near_the_edge(self):
        area = self.settings_area()
        c, s = area.canvas, area.scroll
        self.settle(1.5)                        # (the thumb from opening has faded)
        self.assertFalse(s._shown)
        x = c.winfo_rootx() + c.winfo_width() - self.app.px(4)
        y = c.winfo_rooty() + c.winfo_height() // 2
        c.event_generate("<Motion>", x=c.winfo_width() - self.app.px(4), y=c.winfo_height() // 2,
                         rootx=x, rooty=y)
        pump(self.app, timeout=0.05)
        self.assertTrue(s._shown)

    def test_widens_smoothly(self):
        area = self.settings_area()
        s = area.scroll
        s.flash()
        s._set_hover(True)
        pump(self.app, timeout=0.03)
        w = s._geometry()[3]
        self.assertTrue(self.app.px(SCROLL_W) <= w <= self.app.px(SCROLL_W_HOVER))
        self.settle()
        self.assertEqual(round(s._geometry()[3]), self.app.px(SCROLL_W_HOVER))


class MemoScrollTest(Case):
    def test_memo_text_glides_and_never_bounces(self):
        nw = self.nw
        nw.body.insert("1.0", "\n".join(f"줄 {i}" for i in range(80)))
        nw.body.mark_set("insert", "1.0")
        nw.body.see("1.0")
        self.settle()
        self.wheel(nw.body, -120)
        pump(self.app, timeout=SCROLL_SMOOTH_MS / 3000)
        self.assertTrue(animating(nw.body, "smooth"))
        self.settle()
        self.assertGreater(nw.body.yview()[0], 0.0)
        top = nw.body.yview()[0]
        for _ in range(3):
            self.wheel(nw.body, 120)
        self.settle()
        self.assertEqual(nw.body.yview()[0], 0.0)
        self.assertLess(nw.body.yview()[0], top)


class ReviewScrollTest(Case):
    def test_list_thumb_wheel_goes_through_the_list(self):
        lv = self.nw.list_view
        self.assertEqual(lv.area.scroll.wheel_to, lv.wheel)

    def test_a_jump_by_code_stops_a_glide(self):
        area = self.settings_area()
        c = area.canvas
        self.wheel(c, -120)
        area.to_top()
        self.settle()
        self.assertEqual(c.canvasy(0), 0)


if __name__ == "__main__":
    unittest.main()
