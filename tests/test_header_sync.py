import tempfile
import unittest
from pathlib import Path

from _support import Spy, close_app, make_app, patched, pump


class HeaderSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def test_header_keystroke_does_not_sync_at_once(self):
        with patched(type(self.nw), "sync_from_widgets", Spy()) as m:
            self.nw.header_var.set("제목")
            self.assertEqual(m.call_count, 0)
            pump(self.app, timeout=0.4)                     # > TYPING_SYNC_MS (250)
            self.assertGreaterEqual(m.call_count, 1)        # (an autosave may sync too)

    def test_header_typed_then_closed_is_saved(self):
        nw = self.app.new_window(from_window=self.nw)
        pump(self.app, timeout=0.3)
        nw.header_var.set("닫기 직전 제목")
        self.app.close_window(nw)
        pump(self.app, lambda: nw.pad.id not in self.app.windows, timeout=2)
        self.app.save_now()
        self.assertIn("닫기 직전 제목", (Path(self.tmp.name) / "notes.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
