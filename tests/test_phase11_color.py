"""Phase 11, colour from the note (2026-11-28, backlog item 3): a colour dot on the top bar opens a
palette; the right-click / ⋯ menu has the same swatches at its top."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from ui_common import PALETTE, PopupMenu


class ColorDotTest(unittest.TestCase):
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

    def test_dot_on_the_top_bar(self):
        nw = self.nw
        d = nw.btn_color
        self.assertTrue(d.winfo_ismapped())
        self.assertLess(d.winfo_rootx(), nw.btn_min.winfo_rootx())          # left of −
        self.assertEqual(d.color.upper(), nw.note.color.upper())

    def test_hidden_on_pages_and_folded(self):
        nw = self.nw
        nw.show_list()
        self.settle()
        self.assertFalse(nw.btn_color.winfo_ismapped())
        nw.show_home()
        self.settle()
        self.assertTrue(nw.btn_color.winfo_ismapped())
        nw.toggle_collapse(instant=True)
        self.settle()
        self.assertFalse(nw.btn_color.winfo_ismapped())

    def test_palette_sets_the_colour(self):
        nw = self.nw
        self.app.prefs.custom_colors = ["#123456"]
        menu = nw.color_menu()
        self.assertIsNotNone(menu)
        colors = [c for c, _cv in menu.swatch_cells]
        self.assertEqual(colors[:len(PALETTE)], [c.upper() for _n, c in PALETTE])
        self.assertIn("#123456", colors)
        self.assertEqual(menu.swatch_current, nw.note.color.upper())
        target = PALETTE[3][1].upper()
        menu.choose_swatch(target)
        self.settle(0.1)
        self.assertEqual(nw.note.color.upper(), target)
        self.assertIsNone(PopupMenu.current)                                 # it closed
        self.assertEqual(nw.btn_color.color.upper(), target)                # the dot follows

    def test_menus_have_the_swatches(self):
        nw = self.nw
        menu = nw._more_menu()
        self.assertTrue(menu.swatch_cells)
        PopupMenu.close_current()
        event = type("E", (), {"x_root": nw.win.winfo_rootx() + 60, "y_root": nw.win.winfo_rooty() + 20})()
        menu = nw._top_menu(event)
        self.assertTrue(menu.swatch_cells)


if __name__ == "__main__":
    unittest.main()
