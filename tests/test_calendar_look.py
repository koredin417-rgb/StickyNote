"""Phase 3, Tasks 6-8: the calendar's C header (big month numeral, ⋯ menu), the today icon, and
the small §6.4 items (chip drop, holiday card)."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import anim
import texts
from _support import close_app, make_app, pump
from texts import tr
from ui_common import DATE_ROW_H, PopupMenu


class CalendarLookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        pump(self.app, timeout=0.3)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.toggle_calendar()
        self.settle()
        self.cal = self.nw.calendar

    def tearDown(self):
        PopupMenu.close_current()
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.4):
        pump(self.app, lambda: not self.app.motion.busy(), timeout=1.5)
        pump(self.app, timeout=t)

    # ---- Task 6: the head
    def test_head_texts(self):
        y, m = self.cal.month
        self.assertEqual(self.cal.head_texts(), list(texts.month_head(y, m)))
        self.assertEqual(texts.month_head(2026, 11, lang="ko"), ("11", "11월", "2026년"))
        self.assertEqual(texts.month_head(2026, 11, lang="en"), ("11", "November", "2026"))

    def test_head_buttons_order(self):
        cal = self.cal
        buttons = (cal.btn_today, cal.btn_prev, cal.btn_next, cal.btn_more, cal.btn_close)
        for b in buttons:
            self.assertTrue(b.winfo_ismapped())
        xs = [b.winfo_rootx() for b in buttons]
        self.assertEqual(xs, sorted(xs))
        self.assertFalse(hasattr(cal, "grab") and cal.grab.winfo_ismapped())
        self.assertEqual(cal.head.winfo_height(), self.app.px(DATE_ROW_H) - 2 * cal.edge)

    def test_cal_more_menu(self):
        cal = self.cal
        menu = cal._more_menu()
        self.assertEqual(menu.labels(), [tr("menu_this_month"),
                                         tr("menu_cal_detach" if cal.docked else "menu_cal_attach"),
                                         tr("menu_cal_small" if cal.expanded else "menu_cal_big")])
        PopupMenu.close_current()
        was = cal.docked
        dict((item[0], item[1]) for item in menu.items if item)[menu.labels()[1]]()
        self.settle()
        self.assertNotEqual(self.nw.calendar.docked, was)

    # ---- Task 7: the today icon; paging keeps the size
    def test_today_icon_fades(self):
        cal = self.cal
        bg = cal.colors.bg
        self.assertEqual(cal.btn_today.ink_color.upper(), bg.upper())
        cal.next_month()
        pump(self.app, timeout=anim.FAST / 1000 + 0.6)
        self.assertEqual(cal.btn_today.ink_color.upper(), cal.colors.muted.upper())
        cal.this_month()
        pump(self.app, timeout=0.8)
        month = cal.month
        cal.btn_today._command()                      # on the current month: nothing happens
        pump(self.app, timeout=0.2)
        self.assertEqual(cal.month, month)

    def _sizes_while_paging(self):
        cal = self.cal
        top = cal.top
        sizes = {(top.winfo_width(), top.winfo_height())}
        for step in (cal.next_month, cal.next_month, cal.next_month, cal.this_month):
            step()
            for _ in range(30):
                self.app.root.update()
                sizes.add((top.winfo_width(), top.winfo_height()))
            pump(self.app, timeout=0.05)
        pump(self.app, timeout=0.6)
        sizes.add((top.winfo_width(), top.winfo_height()))
        return sizes

    def test_paging_keeps_size_mini(self):
        self.assertEqual(len(self._sizes_while_paging()), 1)

    def test_paging_keeps_size_big(self):
        self.cal.click_view("big")
        self.settle(0.6)
        self.assertEqual(len(self._sizes_while_paging()), 1)

    # ---- Task 8: §6.4 items
    def test_chip_drop_never_twice(self):
        cal, nw = self.cal, self.nw
        nw.body.insert("1.0", "옮길 메모")
        nw.sync_from_widgets()
        cal.click_view("big")
        self.settle(0.6)
        cal.draw()
        note, today = nw.note, date.today()
        x0, y0, x1, y1, _d = next(cell for cell in cal._cells if cell[4] != today and cell[4].month == today.month)

        class Drop:
            x, y = (x0 + x1) // 2, (y0 + y1) // 2
        cal._chip_drag = {"note": note, "day": today}
        cal._drop_chip(Drop())
        g, tag = cal.grid, f"chip{note.id}"
        self.assertTrue(g.find_withtag("settle"))
        self.assertTrue(g.find_withtag(tag))
        self.assertTrue(all(g.itemcget(i, "state") == "hidden" for i in g.find_withtag(tag)))
        pump(self.app, timeout=anim.FAST / 1000 + 0.5)
        self.assertFalse(g.find_withtag("settle"))
        self.assertTrue(g.find_withtag(tag))
        self.assertTrue(all(g.itemcget(i, "state") in ("", "normal") for i in g.find_withtag(tag)))

    def test_holiday_card_fades_in(self):
        import holidays
        from motion import CLICK_THROUGH_ALPHA
        day = sorted(holidays.in_year(date.today().year))[0]
        card = self.cal.holiday_card
        card.show(day.isoformat())
        self.assertLess(float(card.top.attributes("-alpha")), CLICK_THROUGH_ALPHA - 0.05)
        pump(self.app, timeout=anim.FAST / 1000 + 0.4)
        self.assertAlmostEqual(float(card.top.attributes("-alpha")), CLICK_THROUGH_ALPHA, places=2)


class EnglishHeadTest(unittest.TestCase):
    """The head fits the mini view's width in English (long month names), at 100 % and 150 %."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        pump(self.app, timeout=0.3)
        self.app.set_language("en")
        pump(self.app, timeout=0.3)

    def tearDown(self):
        close_app(self.app)
        texts.set_language("ko")
        self.tmp.cleanup()

    def check(self, nw):
        nw.toggle_calendar()
        pump(self.app, lambda: not self.app.motion.busy(), timeout=1.5)
        pump(self.app, timeout=0.4)
        cal = nw.calendar
        self.assertFalse(cal.expanded)
        px = self.app.px
        self.assertLessEqual(cal.head.winfo_reqwidth() + 2 * cal.edge, cal.top.winfo_width())
        self.assertEqual(cal.btn_today.winfo_width(), px(24))

    def test_head_fits_at_100(self):
        self.check(next(iter(self.app.windows.values())))

    def test_head_fits_at_150(self):
        self.app.scale = 1.5
        nw = self.app.new_window(next(iter(self.app.windows.values())))
        pump(self.app, lambda: not self.app.motion.busy(), timeout=1.5)
        self.check(nw)


if __name__ == "__main__":
    unittest.main()
