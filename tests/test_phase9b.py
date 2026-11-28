"""Phase 9, part B1 (2026-11-28): × on pages and a Reopen notice (Q7), save failures shown (Q8),
one menu for ⋯ and right-click plus a menu in the memo text (U2). Spec: 2026-11-28-phase9b-design.md."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from store import Note
from texts import tr
from ui_common import PopupMenu


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

    @staticmethod
    def fill(nw, header, body):
        nw.set_style("header")
        nw.header_var.set(header)
        nw.body.delete("1.0", "end")
        nw.body.insert("1.0", body)
        nw.sync_from_widgets()

    def toast(self, nw):
        return nw.toast.winfo_ismapped() and str(nw.toast_text.cget("text"))


class CloseTest(Case):
    """Q7: no × on the pages; a Reopen notice after a close; the last note says the app closes."""

    def test_no_close_button_on_pages(self):
        nw = self.nw
        for show in (nw.show_list, nw.show_settings, nw.show_bin):
            show()
            self.settle()
            self.assertFalse(nw.btn_close.winfo_ismapped(), show.__name__)
            self.assertTrue(nw.btn_min.winfo_ismapped(), show.__name__)
            nw.show_home()              # (← from the bin goes to the list, not the memo)
            self.settle()
            self.assertTrue(nw.btn_close.winfo_ismapped(), show.__name__)

    def test_close_offers_reopen(self):
        self.fill(self.nw, "남는 노트", "x")
        other = self.app.new_window(from_window=self.nw)
        self.settle()
        self.fill(other, "닫을 노트", "본문")
        other.close()
        self.settle()
        self.assertEqual(len(self.app.windows), 1)
        self.assertEqual(self.toast(self.nw), tr("toast_closed"))
        self.assertTrue(self.nw.undo_button.winfo_ismapped())
        self.nw._toast_undo()
        self.settle()
        self.assertEqual(len(self.app.windows), 2)

    def test_empty_note_closes_quietly(self):
        other = self.app.new_window(from_window=self.nw)
        self.settle()
        other.close()
        self.settle()
        self.assertFalse(self.toast(self.nw))

    def test_last_note_says_the_app_closes(self):
        self.assertEqual(self.nw.btn_close.tooltip.text, tr("tip_close_last"))
        other = self.app.new_window(from_window=self.nw)
        self.settle()
        self.assertEqual(self.nw.btn_close.tooltip.text, tr("tip_close"))
        other.close()
        self.settle()
        self.assertEqual(self.nw.btn_close.tooltip.text, tr("tip_close_last"))


class SaveFailureTest(Case):
    """Q8: two failed saves in a row show a notice that stays until a save works."""

    def test_notice_until_a_save_works(self):
        store, real = self.app.store, self.app.store.save

        def broken(*a, **k):
            raise OSError("disk full")
        store.save = broken
        self.fill(self.nw, "a", "b")
        self.app.save_now(force=True)
        self.assertFalse(self.toast(self.nw))           # one failure: not yet
        self.app.save_now(force=True)
        self.settle(0.1)
        self.assertEqual(self.toast(self.nw), tr("save_failed"))
        pump(self.app, timeout=4.0)                     # (longer than a notice)
        self.assertEqual(self.toast(self.nw), tr("save_failed"))
        store.save = real
        self.app.save_now(force=True)
        self.settle()
        self.assertFalse(self.toast(self.nw))

    def test_open_folder_in_settings(self):
        self.nw.show_settings()
        self.settle()
        self.assertIn("set_folder", self.nw.settings_view.list_rows)


class BackupNoticeTest(unittest.TestCase):
    """Q8: memos loaded from notes.json.bak say so once."""

    def test_loaded_from_backup(self):
        tmp = tempfile.TemporaryDirectory()
        folder = Path(tmp.name)
        app = make_app(folder)
        pump(app, lambda: len(app.windows) == 1)
        nw = next(iter(app.windows.values()))
        Case.fill(nw, "백업", "본문")
        app.save_now(force=True)
        close_app(app)
        shutil.copy(folder / "notes.json", folder / "notes.json.bak")
        (folder / "notes.json").write_text("{broken", encoding="utf-8")
        app = make_app(folder)
        try:
            pump(app, lambda: len(app.windows) >= 1)
            pump(app, timeout=0.5)
            nw = next(iter(app.windows.values()))
            self.assertEqual(str(nw.toast_text.cget("text")), tr("loaded_backup"))
            self.assertTrue(nw.toast.winfo_ismapped())
        finally:
            close_app(app)
            tmp.cleanup()


class OneMenuTest(Case):
    """U2: ⋯ is the right-click menu (plus the rail's hidden buttons); the text has its own menu."""

    def right_click_labels(self):
        nw = self.nw
        event = type("E", (), {"x_root": nw.win.winfo_rootx() + 60, "y_root": nw.win.winfo_rooty() + 20})()
        labels = nw._top_menu(event).labels()
        PopupMenu.close_current()
        return labels

    def test_more_is_the_right_click_menu(self):
        top = self.right_click_labels()
        more = self.nw._more_menu().labels()
        PopupMenu.close_current()
        self.assertEqual(more[:len(top)], top)

    def test_text_menu(self):
        nw = self.nw
        nw.body.focus_force()
        pump(self.app, timeout=0.1)
        menu = nw._text_menu(nw.body.winfo_rootx() + 20, nw.body.winfo_rooty() + 20)
        labels = menu.labels()
        for key in ("menu_cut", "menu_copy", "menu_paste", "menu_select_all", "tip_bullets", "tip_todo"):
            self.assertTrue(any(lb.startswith(tr(key).split("\n")[0].split(" (")[0]) for lb in labels), key)


if __name__ == "__main__":
    unittest.main()
