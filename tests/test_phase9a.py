"""Phase 9, part A (2026-11-28): Caps Lock shortcuts (Q1), the big calendar's "+N" (Q2), the
typing rail's order (Q3), the keep-on-top icon (Q4), the month icon's colours (Q5), the title
spacing and the Settings colour dot (spec: 2026-11-28-phase9a-fixes-design.md)."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from _support import close_app, make_app, pump
from store import Note
from texts import tr
from ui_common import GLYPH, MARK_CONTRAST, MIN_H, PopupMenu, contrast


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.settle()

    def tearDown(self):
        PopupMenu.close_current()
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def type_text(self, text):
        b = self.nw.body
        b.focus_force()
        pump(self.app, timeout=0.1)
        b.delete("1.0", "end")
        b.insert("1.0", text)

    SHIFT, LOCK, CONTROL = 1, 2, 4

    def key(self, keysym, state):
        """A key as Windows sends it: with Caps Lock, Ctrl+C is keysym "C" with Lock in the state."""
        self.nw.body.focus_force()
        pump(self.app, timeout=0.05)
        self.nw.body.event_generate("<KeyPress>", keysym=keysym, state=state)
        pump(self.app, timeout=0.1)


class CapsLockKeysTest(Case):
    """Q1: with Caps Lock on, Ctrl+C copies; the to-do, bullets and new window need Shift."""

    def test_caps_ctrl_c_copies(self):
        self.type_text("hello")
        self.nw.body.tag_add("sel", "1.0", "1.5")
        self.app.root.clipboard_clear()
        self.key("C", self.CONTROL | self.LOCK)
        self.assertEqual(self.app.root.clipboard_get(), "hello")
        self.assertEqual(self.nw.body.get("1.0", "end-1c"), "hello")

    def test_ctrl_shift_c_makes_a_todo(self):
        self.type_text("hello")
        self.key("C", self.CONTROL | self.SHIFT)
        self.assertNotEqual(self.nw.body.get("1.0", "end-1c"), "hello")

    def test_caps_ctrl_n_makes_a_memo(self):
        self.type_text("first")
        before, windows = self.nw.note, len(self.app.windows)
        self.key("N", self.CONTROL | self.LOCK)
        self.settle()
        self.assertEqual(len(self.app.windows), windows)
        self.assertIsNot(self.nw.note, before)

    def test_ctrl_shift_n_opens_a_window(self):
        windows = len(self.app.windows)
        self.key("N", self.CONTROL | self.SHIFT)
        self.settle()
        self.assertEqual(len(self.app.windows), windows + 1)

    def test_caps_ctrl_w_closes(self):
        self.app.new_window(from_window=self.nw)
        self.settle()
        windows = len(self.app.windows)
        self.key("W", self.CONTROL | self.LOCK)
        self.settle()
        self.assertEqual(len(self.app.windows), windows - 1)


class BigCalendarMoreTest(Case):
    """Q2: "+N" sits in the day-number row; every chip slot keeps a title."""

    def test_more_in_the_number_row(self):
        iso = date.today().isoformat()
        for i in range(8):
            self.app.add_note(Note(header=f"메모 {i}", body="x", style="header", date=iso))
        self.nw.toggle_calendar()
        self.settle()
        cal = self.nw.calendar
        cal.click_view("big")
        self.settle(0.5)
        g = cal.grid
        more = g.find_withtag(f"more{iso}")
        self.assertTrue(more, "no +N in the day row")
        number = g.find_withtag(f"d{iso}")
        self.assertAlmostEqual(g.coords(more[0])[1], g.coords(number[0])[1], delta=1)
        shown = [n for n in self.app.notes.values() if n.date == iso and g.find_withtag(f"chip{n.id}")]
        hidden = int(g.itemcget(more[0], "text").lstrip("+"))
        self.assertGreaterEqual(len(shown), 1)
        self.assertEqual(len(shown) + hidden, 9 if not self.nw.note.is_empty else 8)


class RailOrderTest(Case):
    """Q3: format buttons give way first; the calendar button stays, even with another calendar open."""

    def test_format_buttons_go_first(self):
        nw = self.nw
        nw.set_size(self.app.px(320), self.app.px(320))
        self.settle()
        nw.body.focus_force()
        pump(self.app, timeout=0.15)
        hidden = nw.rail_hidden()
        self.assertTrue(hidden)
        for b in hidden:
            self.assertIn(b, nw.format_buttons)
        self.assertIn(nw.btn_cal, nw.rail_shown())

    def test_calendar_button_shows_while_another_note_has_the_calendar(self):
        other = self.app.new_window(from_window=self.nw)
        self.settle()
        other.toggle_calendar()
        self.settle()
        self.nw._arrange_chrome()
        self.assertIn(self.nw.btn_cal, self.nw.rail_shown())


class KeepOnTopTest(Case):
    """Q4: keep on top has its own icon and words; the pin is the list's."""

    def test_icon_and_words(self):
        self.assertEqual(GLYPH["on_top"], "")
        self.assertEqual(self.nw.btn_pin.glyph, GLYPH["on_top"])
        self.assertEqual(tr("tip_pin"), tr("menu_on_top"))
        self.nw.toggle_pin()
        self.assertEqual(self.nw.btn_pin.glyph, GLYPH["on_top"])
        self.nw.toggle_pin()

    def test_wording(self):
        import texts
        self.assertEqual(texts.TEXTS["menu_on_top"], ("맨 앞에 두기", "Keep on top"))


class MonthIconTest(Case):
    """Q5: the month head's icon fades through a fixed ramp: the picture cache stays bounded."""

    def test_cache_stays_bounded(self):
        self.nw.toggle_calendar()
        self.settle()
        cal = self.nw.calendar
        glyph = cal.btn_today.glyph
        count = lambda: sum(1 for k in self.app.icons._photos if k[0] == glyph)
        for i in range(6):
            cal._page_to((2024, 1 + i))
            self.settle(0.05)
            cal.this_month()
            self.settle(0.05)
        first = count()
        for i in range(6):
            cal._page_to((2023, 1 + i))
            self.settle(0.05)
            cal.this_month()
            self.settle(0.05)
        self.assertEqual(count(), first)
        self.assertLessEqual(first, 8)


class TitleAndSwatchTest(Case):
    def test_no_rule_under_the_title(self):
        self.nw.set_style("header")
        self.settle()
        self.assertEqual(self.nw.header_sep.cget("bg"), self.nw.colors.bg)
        self.assertTrue(self.nw.header_sep.winfo_ismapped())     # (the space stays)

    def test_settings_dot_shows_on_its_own_colour(self):
        self.nw.show_settings()
        self.settle()
        sv = self.nw.settings_view
        card = sv._card_colors().rest                   # (clear cards: the dot sits on its card)
        dots = [d for (_r, _n, _v, d, _c) in sv.list_rows.values() if d is not None]
        self.assertTrue(dots)
        for d in dots:
            self.assertEqual(d.type(d.find_all()[0]), "image")      # a smooth round dot, not a square
            self.assertGreaterEqual(contrast(self.app.root, d._ring, card), MARK_CONTRAST)


class WarmDeepTest(unittest.TestCase):
    """Today's pill (picked "warm deep", 2026-11-28): a yellow theme leans amber, not olive; other
    colours keep their hue; the number stays readable."""

    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def hue(self, color):
        import colorsys
        from ui_common import _rgb
        return colorsys.rgb_to_hls(*_rgb(self.root, color))[0] * 360

    def test_yellow_leans_amber(self):
        from ui_calendar import deep_color
        from ui_common import Colors
        self.assertAlmostEqual(self.hue(deep_color(self.root, Colors.of(self.root, "#FFF4A3"))), 36, delta=4)

    def test_other_hues_keep_theirs(self):
        from ui_calendar import deep_color
        from ui_common import Colors
        for color in ("#CFE6FF", "#FFD6E7", "#CDEFC4"):
            self.assertAlmostEqual(self.hue(deep_color(self.root, Colors.of(self.root, color))),
                                   self.hue(color), delta=4, msg=color)

    def test_readable(self):
        from ui_calendar import deep_color
        from ui_common import PALETTE, TEXT_CONTRAST, Colors
        for _name, color in PALETTE:
            c = Colors.of(self.root, color)
            self.assertGreaterEqual(contrast(self.root, deep_color(self.root, c), c.bg), TEXT_CONTRAST - 0.01)

if __name__ == "__main__":
    unittest.main()
