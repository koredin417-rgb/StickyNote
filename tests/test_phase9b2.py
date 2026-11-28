"""Phase 9 B2 (2026-11-28): grey text reads at 4.5:1 and at least 9 pt (Q9); one wording pass (Q10).
Plan: docs/superpowers/plans/2026-11-28-phase9b2-readable-and-wording.md."""
import glob
import re
import tempfile
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from store import Note
from ui_common import PALETTE, TEXT_CONTRAST, Colors, PopupMenu, contrast, luminance

APP = Path(__file__).resolve().parents[1] / "StickyNote" / "app"


class MutedTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_muted_text_reads(self):
        for name, color in PALETTE:
            for solid in (False, True):
                c = Colors.of(self.root, color, solid=solid)
                self.assertGreaterEqual(contrast(self.root, c.muted_text, c.bg), TEXT_CONTRAST - 0.01, name)
        c = Colors.of(self.root, "#2E2E2E")
        self.assertGreater(luminance(self.root, c.muted_text), luminance(self.root, c.bg))


class ReadableTextTest(unittest.TestCase):
    """Every word on the list, settings and bin pages reads at 4.5:1 and is at least 9 pt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        for h, c in (("장보기", "#FFE0B8"), ("운동", "#CDEFC4")):
            self.app.add_note(Note(header=h, body="본문", color=c, style="header"))
        trashed = self.app.add_note(Note(header="버린 메모", body="x", style="header"))
        self.app.trash_note(trashed.id)         # (the bin page has a card)
        self.settle()

    def tearDown(self):
        PopupMenu.close_current()
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.4):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def labels(self, widget):
        for w in widget.winfo_children():
            if w.winfo_class() == "Label" and str(w.cget("text")).strip() and w.winfo_ismapped():
                yield w
            yield from self.labels(w)

    def size(self, font):
        return abs(tkfont.Font(font=font).actual("size"))

    def check_page(self, name):
        bad = []
        for w in self.labels(self.nw.win):
            fg, bg = w.cget("fg"), w.cget("bg")
            if contrast(self.app.root, fg, bg) < TEXT_CONTRAST - 0.01 or self.size(w.cget("font")) < 9:
                bad.append((w.cget("text")[:30], fg, bg, self.size(w.cget("font"))))
        self.assertEqual(bad, [], name)

    def test_pages(self):
        nw = self.nw
        for name, show in (("list", nw.show_list), ("settings", nw.show_settings), ("bin", nw.show_bin)):
            show()
            self.settle()
            self.check_page(name)
            nw.show_home()
            self.settle()


class WordingTest(unittest.TestCase):
    DYNAMIC = ("hol_", "title_", "style_", "tidy_", "tidy_order_", "cursor_", "min_", "motion_", "color_",
               "sort_", "once_")

    def test_no_stale_words(self):
        import texts
        for key, value in texts.TEXTS.items():
            both = " ".join(value) if isinstance(value, tuple) else str(value)
            self.assertNotIn("날짜 줄", both, key)          # "상단 바" it is (the user's call, B3)
            self.assertNotIn("date row", both.lower(), key)
        self.assertEqual(texts.TEXTS["motion_off"][0], "끔")
        self.assertEqual(texts.TEXTS["auto_off"][0], "끔")
        self.assertEqual(texts.TEXTS["snap_off"][0], "끔")

    def test_every_key_is_used(self):
        import texts
        code = "".join(Path(f).read_text(encoding="utf-8") for f in glob.glob(str(APP / "*.py"))
                       if not f.endswith("texts.py"))
        tsrc = (APP / "texts.py").read_text(encoding="utf-8")
        code += re.sub(r"TEXTS = \{.*?\n\}\n", "", tsrc, flags=re.S)
        unused = [k for k in texts.TEXTS
                  if f'"{k}"' not in code and f"'{k}'" not in code and not k.startswith(self.DYNAMIC)]
        self.assertEqual(unused, [])


if __name__ == "__main__":
    unittest.main()
