"""User feedback, 2026-11-27: the calendar near the screen's edges (after Phase 8)."""
import tempfile
import unittest
from pathlib import Path

import geom
import ui_calendar
from _support import close_app, make_app, pump
from app import App


def make_app_two(folder, screens):
    return App(folder, screens=screens)


class CalendarEdgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.close_hints()
        self.settle()

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def put(self, x, y):
        p = self.nw.pad
        self.app.apply({p.id: (x, y, x + p.width, y + p.height)})
        self.settle()

    def assert_docked_beside(self):
        cal, p = self.nw.calendar, self.nw.pad
        self.assertTrue(cal.docked)
        note, b = geom.pad_box(p), tuple(cal.target_box)
        gap = self.app._gap()
        side = ui_calendar._dock_side(note, b)
        self.assertIn(side, ("left", "right", "above", "below"))
        if side in ("left", "right"):
            self.assertEqual(min(abs(b[0] - note[2]), abs(note[0] - b[2])), gap, (note, b))
        else:
            self.assertEqual(min(abs(b[1] - note[3]), abs(note[1] - b[3])), gap, (note, b))

    def test_big_in_a_corner_stays_docked(self):
        # no side has room for the big view: the click keeps it mini, beside its note (it used to
        # undock to a free spot elsewhere on the screen and stop following its note)
        p = self.nw.pad
        self.put(1920 - p.width - 10, 1040 - p.height - 10)
        self.nw.toggle_calendar()
        self.settle()
        self.assert_docked_beside()
        cal = self.nw.calendar
        cal._click_view_now("big")
        self.settle()
        self.assert_docked_beside()
        self.assertFalse(cal.expanded)
        self.put(400, 300)                              # it still goes along with its note
        self.assert_docked_beside()

    def beside_right_with_room(self, room):
        """The note so that ``room`` px are left right of it, its mini calendar docked there."""
        p = self.nw.pad
        left, top, right, bottom = self.app.usable()[0]
        self.put(right - room - p.width, top + 200)
        self.nw.toggle_calendar()
        self.settle()
        cal = self.nw.calendar
        self.assertEqual(p.calendar_side, "right")
        self.assert_docked_beside()
        return cal

    def test_big_without_room_keeps_its_side(self):
        # "it moves down": a view switch must not hop sides (plan_dock's keep); big has no room on
        # the right, so it stays mini, on the right
        cal = self.beside_right_with_room(300)
        lw, _lh = cal._least_for("big")
        self.assertGreater(lw, 300 - self.app._gap())   # (big's least really does not fit there)
        cal._click_view_now("big")
        self.settle()
        self.assertEqual(self.nw.pad.calendar_side, "right")
        self.assert_docked_beside()
        self.assertFalse(cal.expanded)

    def test_big_with_some_room_fits_its_side(self):
        # room for big's least but not its full size: big, on the same side, no wider than the room
        cal = self.beside_right_with_room(300)
        lw, _lh = cal._least_for("big")
        self.put(self.nw.pad.x - (lw + 40 - 300), self.nw.pad.y)    # (now lw + 40 px right of the note)
        self.assertEqual(self.nw.pad.calendar_side, "right")
        room = self.app.usable()[0][2] - (self.nw.pad.x + self.nw.pad.width) - self.app._gap()
        cal._click_view_now("big")
        self.settle()
        self.assertEqual(self.nw.pad.calendar_side, "right")
        self.assert_docked_beside()
        self.assertTrue(cal.expanded)
        self.assertLessEqual(cal.target_box[2] - cal.target_box[0], room)


    def test_big_survives_replans(self):
        # (review) the click and every later re-plan (a note resize: settle_view; refit) agree: big
        # stays big on its side, docked, where the click put it
        cal = self.beside_right_with_room(300)
        lw, _lh = cal._least_for("big")
        self.put(self.nw.pad.x - (lw + 40 - 300), self.nw.pad.y)
        cal._click_view_now("big")
        self.settle()
        self.assertTrue(cal.expanded)
        box = tuple(cal.target_box)
        cal.settle_view()
        self.settle()
        cal.refit(geom.pad_box(self.nw.pad))
        self.settle()
        self.assertEqual(self.nw.pad.calendar_side, "right")
        self.assert_docked_beside()
        self.assertTrue(cal.expanded)
        self.assertEqual(tuple(cal.target_box), box)

    def test_big_room_is_the_notes_screen(self):
        # (review) two screens side by side: a note near the seam on the left one has no room on its
        # right for big there; big must not straddle onto the next screen
        import ui_calendar as uc
        from geom import Screen
        close_app(self.app)
        self.app = make_app_two(Path(self.tmp.name), [Screen(monitor=(0, 0, 1920, 1080), work=(0, 0, 1920, 1040)),
                                                      Screen(monitor=(1920, 0, 3840, 1080), work=(1920, 0, 3840, 1040))])
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.close_hints()
        self.settle()
        p = self.nw.pad
        left, top, right, bottom = self.app.area_of((10, 10, 20, 20))
        self.put(right - 300 - p.width, top + 200)
        self.nw.toggle_calendar()
        self.settle()
        cal = self.nw.calendar
        self.assertEqual(p.calendar_side, "right")
        cal._click_view_now("big")
        self.settle()
        self.assertLessEqual(cal.target_box[2], right)
        self.assert_docked_beside()
        del uc

if __name__ == "__main__":
    unittest.main()
