"""Backlog item 4 (2026-11-28): the memo list's select mode. Tick memos, move them all to the bin at
once, and one Undo brings them all back. Spec: 2026-11-28-list-select-design.md."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from store import Note
from texts import tr
from ui_common import PopupMenu


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.memos = [self.app.add_note(Note(header=f"메모 {i}", body="x", style="header")) for i in range(5)]
        self.nw.show_list()
        self.settle()
        self.lv = self.nw.list_view

    def tearDown(self):
        PopupMenu.close_current()
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def click(self, note, shift=False):
        self.lv.card_click(note, shift=shift)
        self.settle(0.05)

    def card_height(self, note):
        _outer, card = self.lv.cards[note.id]
        return card.winfo_height()


class SelectModeTest(Case):
    def test_checks_and_bar(self):
        lv = self.lv
        built = self.app.notes[next(i for i in lv.shown_ids() if i in lv.cards)]     # (a card on screen)
        h = self.card_height(built)
        lv.toggle_select()
        self.settle()
        self.assertTrue(lv.selecting)
        self.assertTrue(lv.select_bar.winfo_ismapped())
        self.assertFalse(lv.bin_row.winfo_ismapped())
        self.assertTrue(lv.checks)
        self.assertEqual(self.card_height(built), h)               # the card keeps its height
        self.click(self.memos[1])
        self.assertEqual(lv.ticked, {self.memos[1].id})
        self.assertEqual(str(lv.select_count.cget("text")), tr("list_selected", n=1))
        lv.toggle_select()
        self.settle()
        self.assertFalse(lv.selecting)
        self.assertEqual(lv.ticked, set())
        self.assertFalse(lv.select_bar.winfo_ismapped())
        self.assertTrue(lv.bin_row.winfo_ismapped())

    def test_a_click_ticks_and_opens_nothing(self):
        lv = self.lv
        before = self.nw.note.id
        lv.toggle_select()
        self.settle()
        self.click(self.memos[2])
        self.assertEqual(self.nw.view, "list")
        self.assertEqual(self.nw.note.id, before)
        self.click(self.memos[2])
        self.assertEqual(lv.ticked, set())                         # again: unticked

    def test_shift_ticks_a_run(self):
        lv = self.lv
        lv.toggle_select()
        self.settle()
        ids = lv.shown_ids()
        a, b = self.app.notes[ids[0]], self.app.notes[ids[3]]
        self.click(a)
        self.click(b, shift=True)
        self.assertEqual(lv.ticked, set(ids[:4]))

    def test_select_all_counts_the_search(self):
        lv = self.lv
        lv.toggle_select()
        self.settle()
        lv.search.set("메모 3")
        self.settle()
        lv.select_all()
        self.assertEqual(lv.ticked, {self.memos[3].id})
        lv.search.set("")
        self.settle()
        lv.select_all()
        self.assertEqual(lv.ticked, set(lv.shown_ids()))

    def test_escape_leaves(self):
        lv = self.lv
        lv.toggle_select()
        self.settle()
        lv.search_entry.focus_force()                               # (keys go where the focus is)
        pump(self.app, timeout=0.05)
        lv.search_entry.event_generate("<Escape>")
        self.settle()
        self.assertFalse(lv.selecting)
        self.assertEqual(self.nw.view, "list")                     # (Esc left select mode, not the list)


class TrashManyTest(Case):
    def test_three_to_the_bin_and_one_undo(self):
        lv, nw = self.lv, self.nw
        lv.toggle_select()
        self.settle()
        for n in self.memos[:3]:
            self.click(n)
        lv.trash_ticked()
        self.settle()
        self.assertTrue(all(n.deleted for n in self.memos[:3]))
        self.assertFalse(any(n.deleted for n in self.memos[3:]))
        self.assertFalse(lv.selecting)
        self.assertEqual(str(nw.toast_text.cget("text")), tr("toast_trashed_n", n=3))
        nw._toast_undo()
        self.settle()
        self.assertFalse(any(n.deleted for n in self.memos))

    def test_open_memo_among_them(self):
        lv, nw = self.lv, self.nw
        shown = self.memos[0]
        nw.open_note(shown)
        self.settle()
        nw.show_list()
        self.settle()
        lv.toggle_select()
        self.settle()
        self.click(shown)
        lv.trash_ticked()
        self.settle()
        self.assertNotEqual(nw.note.id, shown.id)                  # its window shows another memo


if __name__ == "__main__":
    unittest.main()
