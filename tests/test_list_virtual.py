"""Phase 5, Task 2: the memo list is a virtual column: only the cards near the view exist."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from store import Note

N = 500


class VirtualListTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        for i in range(N):
            self.app.add_note(Note(header=f"메모 {i}", body=f"w{i:03d}x 본문 " * 6))
        self.nw.show_list()
        pump(self.app, timeout=0.4)
        self.lv = self.nw.list_view

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def scroll(self, f):
        self.lv.area.canvas.yview_moveto(f)
        pump(self.app, timeout=0.08)

    def contiguous(self):
        lv = self.lv
        rows = lv.rows
        for a, b in zip(rows, rows[1:]):
            self.assertEqual(b.y, a.y + a.height)
        for r in rows:
            if r.widget is not None:
                self.assertEqual(r.widget.winfo_y(), r.y)
        self.assertEqual(int(lv.area.inner.cget("height")), rows[-1].y + rows[-1].height)

    def test_500_memos_keep_few_cards(self):
        lv = self.lv
        for k in range(21):
            self.scroll(k / 20)
            self.assertLessEqual(lv.live_cards(), 40)
        last = [r for r in lv.rows if r.kind == "card"][-1]
        self.assertIn(last.key, lv.cards)
        self.assertTrue(lv.cards[last.key][0].winfo_ismapped())

    def test_rows_do_not_overlap(self):
        self.scroll(0.5)
        self.contiguous()

    def test_arrow_keys_reach_unbuilt_cards(self):
        lv = self.lv
        for _ in range(60):
            lv.step_pick(1)
        pump(self.app, timeout=0.1)
        ids = lv.shown_ids()
        self.assertEqual(lv._picked, ids[59])
        outer = lv.cards[ids[59]][0]
        cv = lv.area.canvas
        top, bottom = cv.winfo_rooty(), cv.winfo_rooty() + cv.winfo_height()
        self.assertTrue(top <= outer.winfo_rooty() and outer.winfo_rooty() + outer.winfo_height() <= bottom + 1)
        lv.open_picked()
        pump(self.app, timeout=0.2)
        self.assertEqual(self.nw.note.id, ids[59])

    def test_search_and_fold_on_long_list(self):
        lv = self.lv
        lv.search.set("w123x")
        pump(self.app, timeout=0.6)
        self.assertEqual(len(lv.shown_ids()), 1)
        self.assertEqual(self.app.notes[lv.shown_ids()[0]].header, "메모 123")
        lv.search.set("")
        pump(self.app, timeout=0.6)
        self.app.prefs.list_collapsed = ["others"]
        lv.refresh()
        pump(self.app, timeout=0.1)
        self.assertEqual(lv.live_cards(), 0)
        self.app.prefs.list_collapsed = []
        lv.refresh()
        pump(self.app, timeout=0.1)
        self.assertGreater(lv.live_cards(), 0)

    def test_far_jump_builds_only_the_view_at_once(self):
        lv = self.lv
        before = set(lv.cards)
        lv.area.canvas.yview_moveto(0.6)
        lv._sync_window()                               # one pass, as at a thumb drag's frame
        made = set(lv.cards) - before
        cv = lv.area.canvas
        top, view = cv.canvasy(0), cv.winfo_height()
        in_view = {r.key for r in lv.rows if r.kind == "card" and r.y < top + view and r.y + r.height > top}
        self.assertLessEqual(len(made - in_view), 2)    # the rest come in later passes
        pump(self.app, timeout=0.6)
        self.assertGreater(len(lv.cards), len(in_view))

    def test_view_does_not_shift_when_rows_above_are_measured(self):
        lv = self.lv
        lv.area.canvas.yview_moveto(0.6)
        lv._sync_window()
        cv = lv.area.canvas
        top = cv.canvasy(0)
        first = next(r for r in lv.rows if r.widget is not None and r.y + r.height > top and r.kind == "card")
        self.app.root.update_idletasks()                # (Tk puts the scrolled frame where the view is)
        y0 = lv.cards[first.key][0].winfo_rooty()
        pump(self.app, timeout=0.8)                     # the rows above it get made and measured
        self.assertLessEqual(abs(lv.cards[first.key][0].winfo_rooty() - y0), 1)

    def test_dropped_cards_go_later(self):
        lv = self.lv
        inner = lv.area.inner
        lv.area.canvas.yview_moveto(0.5)
        lv._sync_window()
        alive = sum(1 for r in lv.rows if r.widget is not None)
        hidden = [w for w in inner.winfo_children() if not w.winfo_manager()]
        self.assertGreater(len(hidden), 0)              # let go of, not destroyed in the pass
        self.assertEqual(len(inner.winfo_children()), alive + len(hidden))
        pump(self.app, timeout=1.0)
        self.assertFalse([w for w in inner.winfo_children() if not w.winfo_manager()])

    def test_width_change_remeasures(self):
        px = self.app.px
        self.nw.set_size(px(480), self.nw.pad.height)
        pump(self.app, lambda: not self.app.motion.busy(), timeout=2)
        pump(self.app, timeout=0.5)
        self.scroll(0.5)
        self.contiguous()


if __name__ == "__main__":
    unittest.main()
