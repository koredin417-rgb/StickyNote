"""Phase 5, Task 1: picking a day or a memo in the calendar repaints only those, not the month."""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from _support import Spy, close_app, make_app, patched, pump


class CalendarRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.body.insert("1.0", "달력 메모")
        self.nw.sync_from_widgets()
        self.nw.toggle_calendar()
        self.settle()
        self.cal = self.nw.calendar

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.4):
        pump(self.app, lambda: not self.app.motion.busy(), timeout=2)
        pump(self.app, timeout=t)

    def days_in_month(self):
        return [c[4] for c in self.cal._cells if c[4].month == self.cal.month[1]]

    def test_pick_day_no_full_draw(self):
        cal, g = self.cal, self.cal.grid
        a, b = [d.isoformat() for d in self.days_in_month()[3:5]]
        with patched(cal, "draw", Spy(wraps=cal.draw)) as spy:
            cal.pick_day(a)
            self.assertEqual(spy.call_count, 0)
            items = g.find_withtag("selected")
            self.assertEqual(len(items), 1)
            self.assertEqual(tuple(round(v) for v in g.coords(items[0])), tuple(cal._spots[a][:2]))
            cal.pick_day(b)
            items = g.find_withtag("selected")
            self.assertEqual(len(items), 1)
            self.assertEqual(tuple(round(v) for v in g.coords(items[0])), tuple(cal._spots[b][:2]))
            self.assertEqual(spy.call_count, 0)

    def test_pick_day_big_view_no_full_draw(self):
        cal, g = self.cal, self.cal.grid
        cal.click_view("big")
        self.settle(0.6)
        da, db = self.days_in_month()[3:5]
        with patched(cal, "draw", Spy(wraps=cal.draw)) as spy:
            cal.pick_day(da.isoformat())
            cal.pick_day(db.isoformat())
            self.assertEqual(spy.call_count, 0)
        self.assertEqual(g.itemcget(f"cell{da.isoformat()}", "fill").upper(), cal._big_fill(da, False).upper())
        self.assertEqual(g.itemcget(f"cell{db.isoformat()}", "fill").upper(), cal._big_fill(db, False).upper())

    def test_chip_pick_no_full_draw(self):
        cal, g = self.cal, self.cal.grid
        cal.click_view("big")
        self.settle(0.6)
        note = self.nw.note                     # (the memo the note shows: opening it changes nothing else)
        box = next(b for b in cal._chips if b[4] is note)
        x, y = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        with patched(cal, "draw", Spy(wraps=cal.draw)) as spy:
            cal._click(SimpleNamespace(x=x, y=y, x_root=0, y_root=0))
            pump(self.app, timeout=0.1)
            self.assertEqual(spy.call_count, 0)
            rect = next(i for i in g.find_withtag(f"chip{note.id}") if g.type(i) == "rectangle")
            picked_fill = g.itemcget(rect, "fill")
            cal.unpick()
            self.assertEqual(spy.call_count, 0)
            rest_fill = g.itemcget(rect, "fill")
        self.assertNotEqual(picked_fill.upper(), rest_fill.upper())
        cal.draw()                              # a full draw of the same state looks the same
        rect = next(i for i in g.find_withtag(f"chip{note.id}") if g.type(i) == "rectangle")
        self.assertEqual(g.itemcget(rect, "fill").upper(), rest_fill.upper())


if __name__ == "__main__":
    unittest.main()
