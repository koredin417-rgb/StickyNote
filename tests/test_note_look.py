"""Phase 3, Tasks 2-5: the note's C look (side rail, date row, folded strip, back row)."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import texts
from _support import Spy, close_app, make_app, patched, pump
from texts import tr
from ui_common import (DATE_ROW_H, MARK_CONTRAST, MIN_H, MIN_W, PALETTE, PILE_STEP, RAIL_W, TEXT_CONTRAST,
                       PopupMenu, contrast)


class NoteLookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        pump(self.app, timeout=0.3)
        self.nw = next(iter(self.app.windows.values()))
        self.errors = []
        self.app.root.report_callback_exception = lambda *a: self.errors.append(a[1])

    def tearDown(self):
        PopupMenu.close_current()
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy(), timeout=1.5)
        pump(self.app, timeout=t)

    def size(self, nw, w, h):
        px = self.app.px
        nw.set_size(px(w), px(h))
        self.settle()

    def not_typing(self, nw):
        nw.win.focus_force()
        pump(self.app, timeout=0.15)

    def typing(self, nw):
        nw.body.focus_force()
        pump(self.app, timeout=0.15)

    def nav(self, nw):
        return (nw.btn_memo, nw.btn_window, nw.btn_list, nw.btn_cal, nw.btn_pin)

    def fmt(self, nw):
        return (nw.btn_bold, nw.btn_italic, nw.btn_underline, nw.btn_strike, nw.btn_bullets, nw.btn_todo,
                nw.btn_picture)

    # ---- Task 2: rail and date row
    def test_rail_order(self):
        nw = self.nw
        self.size(nw, 320, 320)
        self.not_typing(nw)
        self.assertEqual(nw.rail_shown(), self.nav(nw))
        self.assertTrue(nw.btn_more.winfo_ismapped())
        last = nw.rail_shown()[-1]
        self.assertLessEqual(last.winfo_rooty() + last.winfo_height(), nw.btn_more.winfo_rooty())
        self.assertEqual(nw.rail.winfo_width(), self.app.px(RAIL_W))

    def test_date_row_texts(self):
        self.assertEqual(self.nw.row_texts(), list(texts.date_row(date.today())))
        self.assertEqual(texts.date_row(date(2026, 11, 25), lang="ko"), ("25", "11월 수요일"))
        self.assertEqual(texts.date_row(date(2026, 11, 25), lang="en"), ("25", "Wed, Nov"))

    def test_more_menu_items(self):
        menu = self.nw._more_menu()             # Phase 9 (U2): the right-click menu, which has these too
        for key in ("menu_style", "menu_trash", "menu_settings", "menu_minimize"):
            self.assertIn(tr(key), menu.labels())

    def test_row_fold_and_menu(self):
        nw = self.nw
        with patched(PopupMenu, "popup", Spy()) as spy:
            nw.row.event_generate("<Button-3>", x=40, y=10, rootx=nw.row.winfo_rootx() + 40,
                                  rooty=nw.row.winfo_rooty() + 10)
            pump(self.app, timeout=0.1)
        self.assertEqual(len(spy.calls), 1)
        x0, y0 = nw.row.winfo_rootx() + 40, nw.row.winfo_rooty() + 10
        for _ in range(2):                              # two clicks in a row: Tk's double-click
            nw.row.event_generate("<ButtonPress-1>", x=40, y=10, rootx=x0, rooty=y0)
            nw.row.event_generate("<ButtonRelease-1>", x=40, y=10, rootx=x0, rooty=y0)
        pump(self.app, lambda: nw.pad.collapsed and not nw.rolling, timeout=1.5)
        self.assertTrue(nw.pad.collapsed)

    def test_rail_contrast(self):
        nw = self.nw
        for _name, color in PALETTE + (("dark", "#1E1E1E"),):
            nw.set_color(color)
            rail_bg = nw.rail.cget("bg")
            for b in nw.rail_shown() + (nw.btn_more,):
                self.assertGreaterEqual(contrast(nw.win, b.ink_color, rail_bg), MARK_CONTRAST, color)
            num = nw.row.find_withtag("text")[0]
            self.assertGreaterEqual(contrast(nw.win, nw.row.itemcget(num, "fill"), nw.colors.bg), TEXT_CONTRAST, color)

    def test_flash_only_date_row(self):
        nw = self.nw
        rail_bg = nw.rail.cget("bg")
        nw.flash()
        pump(self.app, timeout=0.05)
        self.assertNotEqual(nw.bar.cget("bg").upper(), nw.colors.bg.upper())
        self.assertEqual(nw.rail.cget("bg"), rail_bg)
        pump(self.app, timeout=0.6)
        self.assertEqual(nw.bar.cget("bg").upper(), nw.colors.bg.upper())
        self.assertEqual(nw.row.cget("bg").upper(), nw.colors.bg.upper())

    # ---- Task 3: overflow and the format group
    def test_format_group_on_body_focus(self):
        nw = self.nw
        self.size(nw, 400, 520)
        nw.set_style("header")
        pump(self.app, timeout=0.1)
        self.typing(nw)
        for b in self.fmt(nw):
            self.assertIn(b, nw.rail_shown())
        nw.header_entry.focus_force()
        pump(self.app, timeout=0.15)
        for b in self.fmt(nw):
            self.assertNotIn(b, nw.rail_shown())
        self.typing(nw)
        b = nw.btn_bold
        b.event_generate("<ButtonPress-1>", x=4, y=4)
        b.event_generate("<ButtonRelease-1>", x=4, y=4)
        pump(self.app, timeout=0.1)
        self.assertIs(nw.win.focus_get(), nw.body)

    def test_overflow_order(self):
        nw = self.nw
        self.size(nw, 320, 320)
        self.typing(nw)
        # Phase 9 (Q3): the format buttons give way first (picture, then strike), the calendar last
        self.assertEqual(nw.rail_hidden(), (nw.btn_strike, nw.btn_picture))
        self.assertEqual(nw.rail_shown(), self.nav(nw) + (nw.btn_bold, nw.btn_italic, nw.btn_underline,
                                                          nw.btn_bullets, nw.btn_todo))
        labels = nw._more_menu().labels()
        # Phase 9 (U2): ⋯ is the right-click menu, then the rail's hidden buttons at the end
        self.assertEqual(labels[-2:], [b.tooltip.text.split("\n")[0] for b in (nw.btn_strike, nw.btn_picture)])
        PopupMenu.close_current()
        top = len(nw._note_menu(0, 0).labels())
        PopupMenu.close_current()
        self.size(nw, MIN_W, MIN_H)
        self.typing(nw)
        every = set(self.nav(nw) + self.fmt(nw))
        self.assertEqual(set(nw.rail_shown()) | set(nw.rail_hidden()), every)
        self.assertIn(nw.btn_memo, nw.rail_shown())
        top = len(nw._note_menu(0, 0).labels())
        PopupMenu.close_current()
        in_menu = (nw.btn_memo, nw.btn_window, nw.btn_list, nw.btn_cal, nw.btn_pin)   # (once: review fix)
        self.assertEqual(len(nw._more_menu().labels()), top + len([b for b in nw.rail_hidden() if b not in in_menu]))
        last = nw.rail_shown()[-1]
        self.assertLessEqual(last.winfo_rooty() + last.winfo_height(), nw.btn_more.winfo_rooty())

    def test_rail_fits_at_150(self):
        self.app.scale = 1.5
        nw = self.app.new_window(self.nw)
        self.settle()
        self.size(nw, MIN_W, MIN_H)
        self.typing(nw)
        last = nw.rail_shown()[-1]
        self.assertLessEqual(last.winfo_rooty() + last.winfo_height(), nw.btn_more.winfo_rooty())
        self.assertIn(nw.btn_memo, nw.rail_shown())

    # ---- Task 4: secondary views
    def test_list_view_row(self):
        nw = self.nw
        nw.show_list()
        pump(self.app, timeout=0.2)
        self.assertTrue(nw.btn_back.winfo_ismapped())
        self.assertLess(nw.btn_back.winfo_rootx(), nw.row.winfo_rootx())
        self.assertEqual(nw.row_texts(), [tr("title_list")])
        self.assertFalse(nw.btn_close.winfo_ismapped())     # Phase 9 (Q7): ← and Esc go back, no ×
        self.assertTrue(nw.rail.winfo_ismapped())
        nw.go_back()
        pump(self.app, timeout=0.2)
        self.assertFalse(nw.btn_back.winfo_ismapped())
        self.assertEqual(nw.row_texts(), list(texts.date_row(date.today())))

    # ---- Task 5: folded strip, the resize cover, minimize
    def test_folded_strip(self):
        nw = self.nw
        nw.body.insert("1.0", "첫 줄 메모\n둘째 줄")
        nw.sync_from_widgets()
        nw.toggle_collapse(instant=True)
        self.settle()
        self.assertEqual(nw.win.winfo_height(), self.app.px(PILE_STEP))
        self.assertEqual(self.app.px(PILE_STEP), self.app.px(DATE_ROW_H))
        self.assertFalse(nw.rail.winfo_ismapped())
        texts_ = nw.row_texts()
        self.assertEqual(texts_[0], str(date.today().day))
        self.assertTrue(texts_[1].startswith("첫 줄"), texts_)
        self.assertTrue(nw.btn_close.winfo_ismapped())
        nw.toggle_collapse(instant=True)
        self.settle()
        self.assertTrue(nw.rail.winfo_ismapped())

    def test_freeze_cover_keeps_rail(self):
        nw = self.nw
        px = self.app.px
        nw.freeze()
        cover = nw._cover
        self.assertIsNotNone(cover)
        w, h = nw.win.winfo_width(), nw.win.winfo_height()
        nw.win.geometry(f"{w + px(60)}x{h + px(40)}")
        pump(self.app, timeout=0.2)
        e = nw.edge
        rail = cover.find_withtag("rail")
        self.assertTrue(rail)
        x0, y0, x1, y1 = cover.coords(rail[0])
        self.assertEqual(round(y1 - y0), h + px(40) - 2 * e)
        close = cover.find_withtag("close")
        self.assertTrue(close)
        right = (nw.btn_color.winfo_width() + nw.btn_min.winfo_width() + nw.btn_close.winfo_width()   # (the colour
                 + px(10))                                       # dot, - and x: one piece, at the right)
        self.assertGreaterEqual(cover.coords(close[0])[0], w + px(60) - 2 * e - right)
        nw.thaw()
        pump(self.app, timeout=0.1)
        self.assertTrue(nw.frame.winfo_ismapped())

    # ---- review fixes
    def test_unfold_all_restores_rail(self):
        nw = self.nw
        self.size(nw, 320, 320)
        self.not_typing(nw)
        self.app.fold_all(True)
        self.settle()
        self.app.fold_all(False)
        self.settle()
        self.assertEqual(nw.rail_shown(), self.nav(nw))
        nw.toggle_collapse(instant=True)
        self.settle()
        nw.toggle_collapse(instant=True)
        self.settle()
        self.assertEqual(nw.rail_shown(), self.nav(nw))

    def test_fold_from_list_page(self):
        nw = self.nw
        nw.body.insert("1.0", "가나다라 마바사 " * 40)
        nw.sync_from_widgets()
        nw.show_list()
        pump(self.app, timeout=0.2)
        nw.toggle_collapse(instant=True)
        self.settle()
        self.assertFalse(nw.btn_back.winfo_ismapped())
        cv = nw.row
        last = cv.find_withtag("text")[-1]
        self.assertLessEqual(cv.bbox(last)[2], cv.winfo_width())
        nw.toggle_collapse(instant=True)
        self.settle()
        self.assertTrue(nw.btn_back.winfo_ismapped())

    def test_virtual_focus_keeps_rail(self):
        nw = self.nw
        self.typing(nw)
        self.assertTrue(nw._editing)
        with patched(nw, "_arrange_chrome", Spy(wraps=nw._arrange_chrome)) as spy:
            nw.win.event_generate("<FocusIn>", detail="NotifyNonlinearVirtual")
            nw.win.event_generate("<FocusIn>", detail="NotifyVirtual")
            pump(self.app, timeout=0.05)
        self.assertTrue(nw._editing)
        self.assertEqual(len(spy.calls), 0)

    def test_right_click_menu_bins_only_from_the_memo(self):
        nw = self.nw
        seen = []

        def fake_popup(menu, x, y):
            seen.append(menu.labels())

        class Click:
            x_root, y_root = 100, 100
        with patched(PopupMenu, "popup", fake_popup):
            nw._top_menu(Click())
            nw.show_list()
            pump(self.app, timeout=0.1)
            nw._top_menu(Click())
        self.assertIn(tr("menu_trash"), seen[0])
        self.assertNotIn(tr("menu_trash"), seen[1])

    def test_minimize_restore_keeps_size(self):
        nw = self.nw
        h = nw.pad.height
        nw.minimize()
        pump(self.app, lambda: nw.minimized, timeout=2)
        nw.restore()
        pump(self.app, lambda: not nw.rolling, timeout=2)
        self.settle()
        self.assertEqual(nw.pad.height, h)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
