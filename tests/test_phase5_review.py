"""Findings of the Phase 5 whole-branch review, pinned before they were fixed."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from _support import close_app, make_app, pump
from store import Note
from ui_common import animating

TAGS = ("bullet", "todo", "todo_box", "todo_done", "bi")


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        pump(self.app, timeout=0.2)

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    # 1. undo / redo of a toggle over several lines: the tags are what a full pass gives
    def tags(self):
        b = self.nw.body
        return {t: tuple(str(i) for i in b.tag_ranges(t)) for t in TAGS}

    def full(self):
        self.nw._refresh_bullets()
        self.nw._refresh_combined()
        return self.tags()

    def check(self):
        pump(self.app, timeout=0.15)
        now = self.tags()
        self.assertEqual(now, self.full())

    def test_undo_redo_of_multiline_toggles(self):
        nw, b = self.nw, self.nw.body
        b.insert("1.0", "첫 줄\n☑ done a\n☑ done b\n☑ done c\n☑ done d\n끝")
        pump(self.app, timeout=0.2)
        b.edit_separator()
        b.tag_add("sel", "2.0", "5.end")
        nw.toggle_todo()                     # the boxes go
        self.check()
        b.edit_undo()
        self.check()
        b.edit_redo()
        self.check()
        b.tag_remove("sel", "1.0", "end")
        b.tag_add("sel", "1.0", "6.end")
        nw.toggle_bullets()                  # bullets on six lines
        self.check()
        b.edit_undo()
        self.check()

    # 2. the wheel over the list's scroll thumb moves as far as over the list
    def test_thumb_wheel_moves_a_notch(self):
        for i in range(60):
            self.app.add_note(Note(header=f"메모 {i}", body="본문 " * 20))
        self.nw.show_list()
        pump(self.app, timeout=0.4)
        area = self.nw.list_view.area
        y0 = area.canvas.canvasy(0)
        area.scroll._wheel(SimpleNamespace(delta=-120))
        pump(self.app, lambda: not animating(area.canvas, "smooth"), timeout=1)    # (the glide's end)
        self.assertEqual(area.canvas.canvasy(0) - y0, self.app.px(24))

    # 3. the pictures on cards let go of are not held
    def test_card_pictures_not_held_after_scrolling(self):
        for i in range(60):
            note = Note(header=f"그림 {i}", body="본문")
            note.add_image(self.app.store.add_image(Image.new("RGB", (120, 90), (i * 4 % 255, 90, 160))))
            note.style = "image"
            self.app.add_note(note)
        self.nw.show_list()
        pump(self.app, timeout=0.4)
        lv = self.nw.list_view
        for k in list(range(21)) + list(range(20, -1, -1)):
            lv.area.canvas.yview_moveto(k / 20)
            pump(self.app, timeout=0.05)
        pump(self.app, timeout=0.8)
        held = len(getattr(lv, "_shown", []))
        self.assertLessEqual(held, 3 * max(1, lv.live_cards()))


if __name__ == "__main__":
    unittest.main()
