"""Phase 9 whole-branch review (2026-11-28): the fixes, each pinned by a test."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from store import Note
from texts import tr
from ui_common import GLYPH, ICON_BOX, MIN_H, MIN_W, PopupMenu


class Case(unittest.TestCase):
    tips = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name), tips=self.tips)
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

    @staticmethod
    def fill(nw, header, body):
        nw.set_style("header")
        nw.header_var.set(header)
        nw.body.delete("1.0", "end")
        nw.body.insert("1.0", body)
        nw.sync_from_widgets()

    def toast(self, nw):
        return nw.toast.winfo_ismapped() and str(nw.toast_text.cget("text"))

    def icon(self, nw, glyph):
        return str(self.app.icons.photo(glyph, nw.colors.bg, self.app.px(ICON_BOX)))


class TextMenuTest(Case):
    def test_paste_puts_text_in(self):
        nw = self.nw
        nw.win.clipboard_clear()
        nw.win.clipboard_append("붙여 넣은 글")
        nw.body.focus_force()
        pump(self.app, timeout=0.1)
        nw._text_menu(nw.body.winfo_rootx() + 20, nw.body.winfo_rooty() + 20).invoke(tr("menu_paste"))
        self.settle(0.1)
        self.assertIn("붙여 넣은 글", nw.body.get("1.0", "end"))


class StickyTest(Case):
    def break_saves(self):
        store, real = self.app.store, self.app.store.save

        def broken(*a, **k):
            raise OSError("disk full")
        store.save = broken
        self.addCleanup(setattr, store, "save", real)
        for _ in range(2):
            self.app.save_now(force=True)
        self.settle(0.1)

    def test_button_survives_a_repaint(self):
        nw = self.nw
        self.break_saves()
        self.assertEqual(self.toast(nw), tr("save_failed"))
        nw.toggle_pin()                         # (apply_look: the bar's button is painted again)
        self.settle(0.1)
        self.assertEqual(str(nw.undo_button.cget("image")), self.icon(nw, GLYPH["folder"]))
        self.assertEqual(nw.undo_button.tooltip.text, tr("open_folder"))

    def test_notice_comes_back_after_what_covered_it(self):
        nw = self.nw
        self.break_saves()
        nw.show_notice("잠깐")
        self.assertEqual(self.toast(nw), "잠깐")
        nw.hide_undo()                          # (the notice's time is up)
        self.settle(0.1)
        self.assertEqual(self.toast(nw), tr("save_failed"))

    def test_failing_again_keeps_an_undo(self):
        nw = self.nw
        self.break_saves()
        self.fill(nw, "버릴 메모", "x")
        nw.trash_current()
        self.settle(0.1)
        self.assertEqual(self.toast(nw), tr("toast_moved"))
        self.app.save_now(force=True)           # a third failure
        self.settle(0.1)
        self.assertEqual(self.toast(nw), tr("toast_moved"))


class MenuTest(Case):
    def test_short_note_lists_each_command_once(self):
        nw = self.nw
        nw.set_size(self.app.px(MIN_W), self.app.px(MIN_H))
        self.settle()
        nw.body.focus_force()                   # (typing: the format buttons want room too)
        self.settle()
        self.assertTrue(nw.rail_hidden())
        labels = nw._more_menu().labels()
        PopupMenu.close_current()
        self.assertEqual(len(labels), len(set(labels)), labels)

    def test_minimize_follows_top_bar_only(self):
        nw = self.nw
        self.app.prefs.minimize_style = "bar"
        nw._more_menu().invoke(tr("menu_minimize"))
        self.settle()
        self.assertTrue(nw.pad.collapsed)
        self.assertEqual(nw.win.state(), "normal")


class CloseBarTest(Case):
    def test_goes_where_the_keyboard_goes(self):
        app, a = self.app, self.nw
        self.fill(a, "a", "x")
        b = app.new_window(from_window=a)
        self.settle()
        c = app.new_window(from_window=b)
        self.settle()
        self.fill(c, "c", "x")
        app.last_note = None
        c.close()
        self.settle()
        heir = b                                # the newest shown (note_minimized's pick)
        self.assertEqual(self.toast(heir), tr("toast_closed"))
        self.assertFalse(self.toast(a))
        self.assertEqual(heir.undo_button.tooltip.text, tr("menu_reopen"))

    def test_never_on_a_folded_note(self):
        app, a = self.app, self.nw
        b = app.new_window(from_window=a)
        self.settle()
        self.fill(b, "b", "x")
        a.toggle_collapse(instant=True)
        self.settle()
        app.last_note = a
        b.close()
        self.settle()
        self.assertFalse(a.toast.place_info())


class FoldedTipTest(Case):
    tips = True

    def test_no_tip_on_a_folded_note(self):
        nw = self.nw
        self.fill(nw, "접힌 노트", "x")
        nw.toggle_collapse(instant=True)
        self.settle()
        self.assertFalse(nw.show_tip("link"))
        self.assertNotIn("link", self.app.prefs.tips_seen)


class CardIconTest(Case):
    def test_hidden_bin_icon_does_nothing(self):
        nw = self.nw
        note = self.app.add_note(Note(header="그대로", body="x", style="header"))
        nw.show_list()
        self.settle()
        self.assertTrue(nw.list_view.bin_icons)
        for trash in nw.list_view.bin_icons.values():   # (at rest: the pointer is not on the card)
            trash.event_generate("<ButtonRelease-1>")
        self.settle(0.1)
        self.assertIsNone(note.deleted)


if __name__ == "__main__":
    unittest.main()
