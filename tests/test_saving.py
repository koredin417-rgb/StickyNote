"""Phase 6, Task 3: a save with nothing changed returns at once; any change is still written; a
kill during a save leaves a loadable file."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import store
from _support import Spy, close_app, make_app, patched, pump


class SavingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.app = make_app(self.folder)
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        pump(self.app, timeout=0.5)
        self.app.save_now()

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def saved(self):
        return json.loads((self.folder / "notes.json").read_text(encoding="utf-8"))

    def test_save_without_change_skips(self):
        with patched(store.json, "dumps", Spy(wraps=store.json.dumps)) as spy:
            t = time.perf_counter()
            self.app.save_now()
            ms = (time.perf_counter() - t) * 1000
        self.assertEqual(spy.call_count, 0)
        self.assertLess(ms, 1.0)

    def test_any_attribute_change_saves(self):
        self.nw.note.color = "#CFE6FF"
        self.app.save_now()
        self.assertEqual(self.saved()["notes"][0]["color"], "#CFE6FF")
        self.nw.pad.x = self.nw.pad.x + 7
        self.app.save_now()
        self.assertEqual(self.saved()["pads"][0]["x"], self.nw.pad.x)
        self.app.prefs.snap_gap = 9
        self.app.save_now()
        self.assertEqual(self.saved()["prefs"]["snap_gap"], 9)

    def test_quit_writes_in_place_list_change(self):
        self.app.prefs.custom_colors.append("#123456")
        self.app.quit()
        self.assertIn("#123456", self.saved()["prefs"]["custom_colors"])

    def test_kill_during_save_leaves_loadable_file(self):
        before = self.saved()
        self.nw.note.color = "#FFD6E7"

        def killed(*a, **k):
            raise KeyboardInterrupt("killed mid-save")
        with patched(store.os, "replace", killed):
            with self.assertRaises(KeyboardInterrupt):
                self.app.store.save(list(self.app.notes.values()), [self.nw.pad], self.app.prefs)
        self.assertEqual(self.saved(), before)
        self.assertIsNotNone(self.app.store._read(self.app.store.path))


if __name__ == "__main__":
    unittest.main()
