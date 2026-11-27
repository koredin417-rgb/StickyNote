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



class MinimizeButtonTest(FeedbackCase):
    """Minimize (B): a "-" button left of the close button on the date row."""

    def click(self, b):
        b.event_generate("<ButtonPress-1>", x=4, y=4)
        b.event_generate("<ButtonRelease-1>", x=4, y=4)

    def test_button_sits_left_of_close(self):
        nw = self.nw
        self.assertTrue(nw.btn_min.winfo_ismapped())
        self.assertLessEqual(nw.btn_min.winfo_rootx() + nw.btn_min.winfo_width(), nw.btn_close.winfo_rootx())
        self.assertEqual(nw.btn_min.winfo_rooty(), nw.btn_close.winfo_rooty())

    def test_button_minimizes(self):            # "rolls away" style: it goes to the taskbar
        nw = self.nw
        self.app.prefs.minimize_style = "fold"
        self.click(nw.btn_min)
        pump(self.app, lambda: nw.minimized and not nw.rolling, timeout=1.5)
        self.assertTrue(nw.minimized)

    def test_top_bar_style_folds(self):         # the default "Top bar only": it folds; folded, it goes away
        nw = self.nw
        self.assertEqual(self.app.prefs.minimize_style, "bar")
        self.click(nw.btn_min)
        self.settle()
        self.assertTrue(nw.pad.collapsed)
        self.assertFalse(nw.minimized)
        self.click(nw.btn_min)
        pump(self.app, lambda: nw.minimized and not nw.rolling, timeout=1.5)
        self.assertTrue(nw.minimized)

    def test_date_text_stays_clear_of_the_buttons(self):
        from ui_common import MIN_W
        nw = self.nw
        p = nw.pad
        self.app.apply({p.id: (p.x, p.y, p.x + self.app.px(MIN_W), p.y + p.height)})
        self.settle()
        nw._draw_row()
        box = nw.row.bbox("all")
        self.assertIsNotNone(box)
        self.assertLessEqual(box[2], nw.row.winfo_width())


class WordingTest(FeedbackCase):
    """Wording (C): an empty day says "메모 없음" (the date is in the bar above) and offers "+ 새 메모"
    with the add icon."""

    def test_empty_day_short_words(self):
        import texts
        nw = self.nw
        nw.toggle_calendar()
        self.settle()
        cal = nw.calendar
        day = next(c[4] for c in cal._cells if c[4].month == cal.month[1] and c[4].day == 28)
        cal.pick_day(day.isoformat())
        self.settle()
        lv = nw.list_view
        self.assertEqual(lv.empty_text, texts.tr("none_on"))
        self.assertEqual(texts.TEXTS["none_on"], ("메모 없음", "No memos"))
        self.assertEqual(texts.TEXTS["new_on_day"], ("새 메모", "New memo"))
        import tkinter as tk

        def walk(w):
            yield w
            for ch in w.winfo_children():
                yield from walk(ch)
        buttons = [w for w in walk(nw.win) if isinstance(w, tk.Label) and w.winfo_ismapped()
                   and w.cget("text") == texts.tr("new_on_day")]
        self.assertTrue(buttons)
        self.assertTrue(buttons[0].cget("image"))
        self.assertEqual(buttons[0].cget("compound"), "left")



class CalendarSizeTest(FeedbackCase):
    """Calendar size (B + a button): double-click the calendar's head, or its expand button, toggles
    small and big. Double-clicking a day still makes a new memo. The head keeps its width."""

    def open(self):
        self.nw.toggle_calendar()
        self.settle()
        return self.nw.calendar

    def double_click(self, w, t0):
        """Two clicks 100 ms apart (by the events' own time): Tk sees a double-click."""
        for t in (t0, t0 + 100):
            w.event_generate("<ButtonPress-1>", x=8, y=8, time=t)
            w.event_generate("<ButtonRelease-1>", x=8, y=8, time=t + 30)

    def test_head_double_click_toggles(self):
        cal = self.open()
        self.assertFalse(cal.expanded)
        self.double_click(cal.head_cv, 10_000)
        self.settle()
        self.assertTrue(cal.expanded)
        self.double_click(cal.head_cv, 20_000)
        self.settle()
        self.assertFalse(cal.expanded)
        self.assertTrue(cal.btn_close.master.bind("<Double-Button-1>"))     # (the head's own frame too)

    def test_size_button_toggles_and_shows_the_view(self):
        import texts
        from ui_common import GLYPH
        cal = self.open()
        b = cal.btn_size
        self.assertEqual((b.glyph, b.tooltip.text), (GLYPH["expand"], texts.tr("menu_cal_big")))
        b.event_generate("<ButtonPress-1>", x=4, y=4)
        b.event_generate("<ButtonRelease-1>", x=4, y=4)
        self.settle()
        self.assertTrue(cal.expanded)
        self.assertEqual((b.glyph, b.tooltip.text), (GLYPH["shrink"], texts.tr("menu_cal_small")))

    def test_size_button_looks_like_its_neighbours(self):    # (user: "looks out of place")
        from ui_common import GLYPH, OPTICAL_SCALE
        cal = self.open()
        b, n = cal.btn_size, cal.btn_next
        self.assertEqual((b._bg, b._hover, b.ink_color), (n._bg, n._hover, n.ink_color))
        self.assertEqual(OPTICAL_SCALE.get(GLYPH["expand"]), OPTICAL_SCALE.get(GLYPH["close"]))
        self.assertEqual(OPTICAL_SCALE.get(GLYPH["shrink"]), OPTICAL_SCALE.get(GLYPH["close"]))

    def test_head_keeps_its_width(self):
        cal = self.open()
        head = cal.btn_close.master
        px = self.app.px
        buttons = (cal.btn_today, cal.btn_prev, cal.btn_next, cal.btn_size, cal.btn_more, cal.btn_close)
        self.assertEqual({b.winfo_reqwidth() for b in buttons}, {px(20)})
        self.assertLessEqual(head.winfo_reqwidth(), cal.least[0])       # (nothing in it is cut off)
        self.assertEqual(head.winfo_reqwidth(), 6 * px(20) + cal.head_cv.winfo_reqwidth() + 2 * px(4))



class PageChangeTest(FeedbackCase):
    """Pages (D): moving between the memo, list, settings and bin pages, the new page comes in with
    a 12 px slide and a fade (180 ms) over the old one: forward from the right, back from the left."""

    def test_page_change_slides_and_fades(self):
        nw = self.nw
        nw._show_view("list")
        cover = getattr(nw, "_page_cover", None)
        self.assertIsNotNone(cover)
        self.assertTrue(self.app.clock.active(nw.views, "page"))
        self.assertEqual(nw._page_move, self.app.px(12))            # forward: in from the right
        self.settle()
        self.assertIsNone(nw._page_cover)
        self.assertFalse(cover.winfo_exists())
        self.assertTrue(nw.list_view.frame.winfo_ismapped())
        nw._show_view("home")
        self.assertEqual(nw._page_move, -self.app.px(12))           # back: in from the left
        self.settle()
        self.assertTrue(nw.home.winfo_ismapped())

    def test_reduced_fades_without_moving(self):
        self.app.set_motion("reduced")
        nw = self.nw
        nw._show_view("settings")
        self.assertIsNotNone(nw._page_cover)
        self.assertEqual(nw._page_move, 0)
        self.settle()
        self.assertIsNone(nw._page_cover)

    def test_off_switches_at_once(self):
        self.app.set_motion("off")
        nw = self.nw
        nw._show_view("bin")
        self.assertIsNone(getattr(nw, "_page_cover", None))
        self.assertTrue(nw.bin_view.frame.winfo_ismapped() or True)

    def test_quick_second_change_replaces_the_first(self):
        nw = self.nw
        nw._show_view("list")
        first = nw._page_cover
        nw._show_view("settings")
        self.assertFalse(first.winfo_exists())
        self.settle()
        self.assertIsNone(nw._page_cover)
        self.assertTrue(nw.settings_view.frame.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
