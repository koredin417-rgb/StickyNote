"""The UI choices picked after Phase 8 (2026-11-27): menus B, pages D, calendar hover B, minimize B,
wording C, calendar size B plus an expand button. Plan: docs/superpowers/plans/2026-11-27-feedback-ui.md"""
import tempfile
import time
import unittest
from pathlib import Path

import anim
from _support import close_app, make_app, patched, pump
from ui_common import MENU_FADE_MS, FontPicker, PopupMenu


class FeedbackCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.close_hints()
        self.settle()

    def tearDown(self):
        PopupMenu.close_current()
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def first_frame(self):
        clock = self.app.clock
        end = time.perf_counter() + 0.2
        while not clock._moves and time.perf_counter() < end:      # (the first frame queued its move)
            self.app.root.update()
        moves = dict(clock._moves)
        return moves


class MenuMotionTest(FeedbackCase):
    """Menus (B): they drop 6 px into place while fading in (120 ms), and fade out (80 ms) on close."""

    def open_menu(self, y=300):
        menu = PopupMenu(self.app, self.nw.win).add("A", lambda: None).add("B", lambda: None)
        menu.popup(400, y)
        return menu

    def test_menu_drops_into_place(self):
        ys = []
        menu = self.open_menu()
        y_end = menu.top.winfo_rooty()
        real = self.app.clock.move

        def move(win, x, y, w=None, h=None):
            if win is menu.top:
                ys.append(y)
            return real(win, x, y, w, h)
        with patched(self.app.clock, "move", move):
            self.settle(0.05)
        self.assertTrue(ys, "the menu never moved: it does not drop")
        self.assertLess(ys[0], 300)
        self.assertGreaterEqual(ys[0], 300 - self.app.px(6))
        self.assertEqual(ys[-1], 300)
        self.assertEqual(menu.top.winfo_rooty(), 300)
        self.assertAlmostEqual(float(menu.top.attributes("-alpha")), 1.0, places=2)
        del y_end

    def test_menu_fades_out_on_close(self):
        menu = self.open_menu()
        self.settle()
        top = menu.top
        menu.close()
        self.assertIsNone(PopupMenu.current)            # let go at once (a new menu may open)
        self.assertTrue(top.winfo_exists())             # ... but still there, fading
        a = self.app.clock._anims.get((id(top), "alpha"))
        self.assertIsNotNone(a)
        self.assertEqual(a.ms, anim.exit_ms(MENU_FADE_MS))
        self.assertIs(a.ease, anim.ease_in)
        pump(self.app, lambda: not top.winfo_exists(), timeout=0.5)
        self.assertFalse(top.winfo_exists())

    def test_menu_off_mode_closes_at_once(self):
        self.app.set_motion("off")
        menu = self.open_menu()
        top = menu.top
        menu.close()
        pump(self.app, lambda: not top.winfo_exists(), timeout=0.1)
        self.assertFalse(top.winfo_exists())

    def test_font_picker_drops_and_fades(self):
        picker = FontPicker(self.nw.frame, self.app, lambda f: None)
        picker.recolor(self.nw.colors)
        picker.pack()
        self.settle(0.05)
        picker.open()
        top = picker.popup
        self.assertTrue(self.app.clock.active(top, "alpha"))
        self.assertTrue(self.app.clock.active(top, "box"))
        self.settle()
        picker.close()
        self.assertIsNone(picker.popup)
        pump(self.app, lambda: not top.winfo_exists(), timeout=0.5)
        self.assertFalse(top.winfo_exists())



class CalendarHoverTest(FeedbackCase):
    """Calendar hover (B): the day under the mouse fades in (120 ms), the one left fades out (180 ms),
    through a fixed ramp of 5 colours (no new picture per frame)."""

    def calendar(self, big=False):
        self.nw.toggle_calendar()
        self.settle()
        cal = self.nw.calendar
        if big:
            cal.set_view("big")
            self.settle()
        from datetime import date
        days = [c[4] for c in cal._cells if c[4].month == cal.month[1] and c[4] != date.today()
                and c[4].isoformat() != cal.selected]
        return cal, days

    def test_mini_hover_fades_in_and_out(self):
        cal, days = self.calendar()
        g, c = cal.grid, cal.colors
        d = days[3]
        cal._set_hover(d)
        self.assertTrue(self.app.clock.active(g, "hover_in"))
        item = g.find_withtag("hover")
        self.assertTrue(item)
        tw, th = cal._spots[d.isoformat()][2:]
        self.assertNotEqual(g.itemcget(item[0], "image"), str(cal._tile(c.hover, tw, th)))   # not solid at once
        self.settle()
        self.assertEqual(g.itemcget(g.find_withtag("hover")[0], "image"), str(cal._tile(c.hover, tw, th)))
        cal._set_hover(None)
        self.assertTrue(self.app.clock.active(g, "hover_out"))
        self.assertTrue(g.find_withtag("hover_out"))
        self.settle()
        self.assertFalse(g.find_withtag("hover_out"))
        self.assertFalse(g.find_withtag("hover"))

    def test_hover_tiles_stay_bounded(self):
        cal, days = self.calendar()
        for d in days[:6] * 3:
            cal._set_hover(d)
            pump(self.app, timeout=0.03)
        cal._set_hover(None)
        self.settle()
        sizes = {(w, h) for (_col, w, h) in cal._tiles}
        self.assertLessEqual(len(cal._tiles), 6 * len(sizes) + 2)   # (the ramp's 5 + the selection's)

    def test_big_hover_fades_the_cell(self):
        cal, days = self.calendar(big=True)
        g = cal.grid
        d = days[3]
        tag = f"cell{d.isoformat()}"
        cal._set_hover(d)
        self.assertTrue(self.app.clock.active(g, f"hover:{d.isoformat()}"))
        self.assertNotEqual(g.itemcget(tag, "fill"), cal._big_fill(d, True))
        self.settle()
        self.assertEqual(g.itemcget(tag, "fill"), cal._big_fill(d, True))
        cal._set_hover(None)
        self.settle()
        self.assertEqual(g.itemcget(tag, "fill"), cal._big_fill(d, False))


if __name__ == "__main__":
    unittest.main()
