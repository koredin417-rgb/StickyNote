"""Phase 9, part B3 (2026-11-28): tips at the right moment (U1). No first-run wall of tips: each
gesture gets one short tip, once, in the bottom bar (picked style A: the dark bar, with ×), and a
"Keys and gestures" page lists everything. Spec: 2026-11-28-phase9b-design.md, B3."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from store import TIPS, NoteStore, Prefs
from texts import tr
from ui_common import PopupMenu


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name), tips=True)
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


class NoWallTest(Case):
    def test_no_tips_at_start(self):
        pump(self.app, timeout=0.6)
        self.assertIsNone(getattr(self.nw, "hints", None))
        self.assertFalse(self.toast(self.nw))
        self.assertEqual(self.app.prefs.tips_seen, [])

    def test_tips_seen_is_cleaned(self):
        self.assertEqual(Prefs(tips_seen=["link", "bogus", "link", 3]).tips_seen, ["link"])
        self.assertEqual(Prefs(tips_seen="link").tips_seen, [])
        self.assertEqual(set(TIPS), {"link", "close", "fold", "calendar"})

    def test_tips_seen_saved(self):
        self.assertTrue(self.nw.show_tip("calendar"))
        self.app.save_now(force=True)
        data = NoteStore(Path(self.tmp.name)).load()
        self.assertEqual(data.prefs.tips_seen, ["calendar"])


class TipBarTest(Case):
    def test_once_with_close_button(self):
        nw = self.nw
        self.assertTrue(nw.show_tip("calendar"))
        self.settle(0.1)
        self.assertEqual(self.toast(nw), tr("once_calendar"))
        self.assertTrue(nw.undo_button.winfo_ismapped())          # the ×
        self.assertEqual(nw.undo_button.tooltip.text, tr("close_tip"))
        pump(self.app, timeout=4.0)                                 # (longer than a notice)
        self.assertEqual(self.toast(nw), tr("once_calendar"))
        nw._toast_undo()
        self.settle(0.1)
        self.assertFalse(self.toast(nw))
        self.assertFalse(nw.show_tip("calendar"))                   # never again
        nw.show_undo_action(tr("toast_closed"), lambda: None)       # (the button is Undo again)
        self.assertEqual(nw.undo_button.tooltip.text, tr("undo"))

    def test_long_tip_wraps_in_a_narrow_note(self):
        nw = self.nw
        nw.win.geometry("220x300")
        self.settle()
        nw.show_tip("link")
        self.settle(0.1)
        self.assertLessEqual(nw.toast.winfo_reqwidth(), nw.main.winfo_width())


class MomentTest(Case):
    def test_first_close(self):
        self.fill(self.nw, "남는 노트", "x")
        for expected in (tr("once_close"), tr("toast_closed")):
            other = self.app.new_window(from_window=self.nw)
            self.settle()
            self.fill(other, "닫을 노트", "본문")
            other.close()
            self.settle()
            self.assertEqual(self.toast(self.nw), expected)
            self.nw.hide_undo()

    def test_first_fold(self):
        nw = self.nw
        self.fill(nw, "접을 노트", "본문")
        nw.toggle_collapse(instant=True)
        self.settle()
        self.assertTrue(nw.pad.collapsed)
        shown = " ".join(nw.row_texts())
        self.assertIn(tr("once_fold")[:6], shown)
        nw.toggle_collapse(instant=True)
        self.settle()
        nw.toggle_collapse(instant=True)
        self.settle()
        shown = " ".join(nw.row_texts())
        self.assertNotIn(tr("once_fold")[:6], shown)
        self.assertIn("접을 노트", shown)

    def test_fold_tip_goes_after_a_while(self):
        nw = self.nw
        self.fill(nw, "접을 노트", "본문")
        nw.toggle_collapse(instant=True)
        self.settle()
        nw._end_fold_tip()                      # (what TIP_MS later does)
        self.assertIn("접을 노트", " ".join(nw.row_texts()))

    def test_first_calendar(self):
        nw = self.nw
        nw.toggle_calendar()
        self.settle()
        self.assertEqual(self.toast(nw), tr("once_calendar"))
        nw.hide_undo()
        nw.toggle_calendar()
        self.settle()
        nw.toggle_calendar()
        self.settle()
        self.assertFalse(self.toast(nw))

    def test_first_link(self):
        app, nw = self.app, self.nw
        other = app.new_window(from_window=nw)
        self.settle()
        a, b = nw.pad.id, other.pad.id
        if not app.links.linked(a, b):
            self.skipTest("the new note does not touch this one here")
        app.unlink(b)
        self.assertTrue(app.link_drop([b], a))          # a new link: the drop says so
        self.assertFalse(app.link_drop([b], a))         # already linked
        self.assertTrue(other.show_tip("link"))
        self.settle(0.1)
        self.assertEqual(self.toast(other), tr("once_link"))


class KeysPageTest(Case):
    def labels(self, widget):
        for w in widget.winfo_children():
            if w.winfo_class() == "Label" and w.winfo_ismapped():
                yield str(w.cget("text"))
            yield from self.labels(w)

    def test_in_the_menu(self):
        labels = self.nw._more_menu().labels()
        PopupMenu.close_current()
        self.assertTrue(any(lb.startswith(tr("menu_keys")) for lb in labels), labels)
        self.assertFalse(any(lb.startswith("조작 안내") for lb in labels))

    def test_opens_in_settings(self):
        nw = self.nw
        nw.show_keys()
        self.settle()
        self.assertEqual(nw.view, "settings")
        self.assertEqual(nw.settings_view.opened, "set_keys")
        shown = list(self.labels(nw.settings_view.pages["set_keys"]))
        rows = nw.settings_view.key_rows            # (the redesign: each key a keycap of its own)
        for combo, caps in (("Ctrl+Shift+T", ["Ctrl", "Shift", "T"]), ("Ctrl+W", ["Ctrl", "W"])):
            self.assertEqual([c.cget("text") for c in rows[combo]], caps)
            self.assertTrue(all(str(c.cget("image")) for c in rows[combo]), combo)    # drawn, smooth
        for text in ("Alt", tr("keys_mouse")):
            self.assertTrue(any(text in s for s in shown), text)
        nw.go_back()                            # back: the settings list, then the memo
        self.settle()
        self.assertEqual((nw.view, nw.settings_view.opened), ("settings", None))
        self.assertIn("set_keys", nw.settings_view.list_rows)


if __name__ == "__main__":
    unittest.main()
