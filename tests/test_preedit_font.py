import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump


class PreeditFontTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def test_same_style_reuses_font(self):
        a = self.nw._preedit_font_for(True, False)
        self.assertIs(a, self.nw._preedit_font_for(True, False))
        self.assertIsNot(a, self.nw._preedit_font_for(False, False))
        self.assertTrue(a.cget("underline"))
        self.assertEqual(a.cget("weight"), "bold")

    def test_font_change_gives_new_font(self):
        a = self.nw._preedit_font_for(False, False)
        self.nw.note.font_size += 2
        b = self.nw._preedit_font_for(False, False)
        self.assertIsNot(a, b)
        self.assertEqual(b.cget("size"), self.nw.note.font_size)


if __name__ == "__main__":
    unittest.main()
