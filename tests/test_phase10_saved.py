"""Phase 10, task 6 (2026-11-28): the saved dot (K). After a pause in typing, once the memo is saved,
a small dot by the date fades in and out; a failed save shows it red until a save works."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from ui_common import SAVED_DOT_MS, SAVED_DOT_PAUSE_MS


class SavedDotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.body.focus_force()
        pump(self.app, timeout=0.3)

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def type(self, text):
        self.nw.body.insert("end", text)
        pump(self.app, timeout=0.05)               # (<<Modified>>: the note reads it as typed)

    def dot(self):
        return self.nw.row.find_withtag("saved")

    def test_after_a_pause(self):
        self.type("장보기")
        self.app.save_now()
        self.assertFalse(self.dot())                # not at once
        pump(self.app, lambda: bool(self.dot()), timeout=SAVED_DOT_PAUSE_MS / 1000 + 1)
        self.assertTrue(self.dot())
        pump(self.app, lambda: not self.dot(), timeout=SAVED_DOT_MS / 1000 + 1)
        self.assertFalse(self.dot())                # it fades away

    def test_not_while_typing(self):
        self.type("장")
        self.app.save_now()
        for ch in "보기 목록":                        # typing on through the pause
            pump(self.app, timeout=SAVED_DOT_PAUSE_MS / 4000)
            self.type(ch)
        self.assertFalse(self.dot())

    def test_failed_is_red_until_a_save_works(self):
        store, real = self.app.store, self.app.store.save

        def broken(*a, **k):
            raise OSError("disk full")
        store.save = broken
        self.type("못 저장")
        self.app.save_now(force=True)
        pump(self.app, timeout=0.05)
        self.assertTrue(self.dot())
        self.assertEqual(str(self.nw._dot_fill).upper(), str(self.nw.colors.danger).upper())
        pump(self.app, timeout=SAVED_DOT_MS / 1000 + 0.5)
        self.assertTrue(self.dot())                 # it stays
        store.save = real
        self.app.save_now(force=True)
        pump(self.app, timeout=0.1)
        self.assertNotEqual(str(self.nw._dot_fill).upper() if self.dot() else "",
                            str(self.nw.colors.danger).upper())

    def test_none_on_pages(self):
        self.type("목록 보기")
        self.nw.show_list()
        self.app.save_now()
        pump(self.app, timeout=SAVED_DOT_PAUSE_MS / 1000 + 0.3)
        self.assertFalse(self.dot())


    def test_red_stays_over_a_flash_already_due(self):
        self.type("저장됨")
        self.app.save_now()                         # works: a flash is due after the pause
        store, real = self.app.store, self.app.store.save

        def broken(*a, **k):
            raise OSError("disk full")
        store.save = broken
        self.type(" 다시")
        self.app.save_now(force=True)               # fails before the flash came
        pump(self.app, timeout=SAVED_DOT_PAUSE_MS / 1000 + SAVED_DOT_MS / 1000 + 0.3)
        self.assertTrue(self.dot())
        self.assertEqual(str(self.nw._dot_fill).upper(), str(self.nw.colors.danger).upper())
        store.save = real


if __name__ == "__main__":
    unittest.main()
