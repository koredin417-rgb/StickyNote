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


if __name__ == "__main__":
    unittest.main()
