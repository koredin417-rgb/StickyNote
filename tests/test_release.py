import gc
import tempfile
import unittest
import weakref
from pathlib import Path

from _support import close_app, make_app, pump


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def _closed_ref(self):
        first = next(iter(self.app.windows.values()))
        nw = self.app.new_window(from_window=first)
        nw.header_var.set("x")
        nw.show_list()
        pump(self.app, timeout=0.3)
        ref = weakref.ref(nw)
        self.app.close_window(nw)
        del nw
        pump(self.app, lambda: len(self.app.windows) == 1, timeout=2)
        pump(self.app, timeout=0.3)
        gc.collect()
        return ref

    def test_closed_window_is_freed(self):
        self.assertIsNone(self._closed_ref()())

    def test_set_language_frees_old_windows(self):
        old = [weakref.ref(w) for w in self.app.windows.values()]
        self.app.set_language("en" if self.app.prefs.language == "ko" else "ko")
        pump(self.app, timeout=0.5)
        gc.collect()
        self.assertTrue(all(r() is None for r in old))
        self.assertEqual(len(self.app.windows), 1)

    def test_last_window_close_quits_and_saves(self):
        only = next(iter(self.app.windows.values()))
        only.body.insert("1.0", "keep me")
        only.sync_from_widgets()
        self.app.close_window(only)
        pump(self.app, lambda: self.app.closed, timeout=2)
        self.assertTrue(self.app.closed)
        self.assertIn("keep me", (Path(self.tmp.name) / "notes.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
