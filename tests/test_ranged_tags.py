"""Phase 5, Task 3: typing re-tags only the lines it touched; the tags stay what a full pass gives."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, patched, pump

TAGS = ("bullet", "todo", "todo_box", "todo_done", "bi")


class RangedTagsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        pump(self.app, timeout=0.2)

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def tags(self):
        b = self.nw.body
        return {t: tuple(str(i) for i in b.tag_ranges(t)) for t in TAGS}

    def full(self):
        self.nw._refresh_bullets()
        self.nw._refresh_combined()
        return self.tags()

    def test_typing_retags_only_near_lines(self):
        nw, b = self.nw, self.nw.body
        lines = [("• " if i % 3 == 0 else "☐ " if i % 3 == 1 else "") + f"줄 {i}" for i in range(3000)]
        nw._edit(lambda: b.insert("1.0", "\n".join(lines)))
        nw._after_edit()
        pump(self.app, timeout=0.2)
        b.mark_set("insert", "1500.3")
        rows = []

        def spy(real):
            def f(tag, *idx):
                rows.extend(int(str(b.index(i)).split(".")[0]) for i in idx)
                return real(tag, *idx)
            return f
        with patched(b, "tag_add", spy(b.tag_add)), patched(b, "tag_remove", spy(b.tag_remove)):
            b.insert("insert", "가")
            pump(self.app, timeout=0.15)
        self.assertTrue(rows)
        self.assertTrue(all(1499 <= r <= 1501 for r in rows), (min(rows), max(rows)))

    def test_tags_still_right(self):
        nw, b = self.nw, self.nw.body
        nw._edit(lambda: b.insert("1.0", "첫 줄\n• 둘\n☐ 셋\n☑ 넷\n다섯"))
        nw._after_edit()
        pump(self.app, timeout=0.15)
        b.mark_set("insert", "end-1c")
        b.insert("insert", "\n• 새 줄")                    # a bullet line typed
        pump(self.app, timeout=0.15)
        now = self.tags()
        self.assertEqual(now, self.full())
        b.mark_set("insert", "3.0")
        b.delete("3.0 -1c")                                 # two lines joined
        pump(self.app, timeout=0.15)
        now = self.tags()
        self.assertEqual(now, self.full())
        b.mark_set("insert", "2.0")
        b.insert("insert", "가\n• 나\n☐ 다\n")              # three lines pasted
        pump(self.app, timeout=0.15)
        now = self.tags()
        self.assertEqual(now, self.full())
        b.tag_add("sel", "2.0", "4.end")                    # bold, then italic, over lines
        nw.toggle_format("b")
        b.tag_remove("sel", "1.0", "end")
        b.tag_add("sel", "3.0", "5.end")
        nw.toggle_format("i")
        pump(self.app, timeout=0.15)
        b.mark_set("insert", "4.1")
        b.insert("insert", "굵")                            # typed inside bold + italic
        pump(self.app, timeout=0.15)
        now = self.tags()
        self.assertEqual(now, self.full())
        b.edit_undo()                                       # undo: not seen by the text proxy
        pump(self.app, timeout=0.15)
        now = self.tags()
        self.assertEqual(now, self.full())


if __name__ == "__main__":
    unittest.main()
