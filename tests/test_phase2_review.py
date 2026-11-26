"""Findings of the Phase 2 whole-branch review, pinned before they were fixed."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import anim
from _support import Spy, close_app, make_app, patched, pump


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        pump(self.app, timeout=0.5)
        self.nw = next(iter(self.app.windows.values()))
        self.errors = []
        self.app.root.report_callback_exception = lambda *a: self.errors.append(a[1])

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def open_calendar(self):
        self.nw.toggle_calendar()
        pump(self.app, lambda: not self.app.motion.busy(), timeout=1)
        pump(self.app, timeout=0.4)
        return self.nw.calendar

    def settled(self):
        return pump(self.app, lambda: not self.app.motion.busy() and self.app._chain is None, timeout=1.5)

    # 1. Off / Reduced: closing the calendar
    def _close_calendar_in(self, mode):
        self.app.set_motion(mode)
        self.open_calendar()
        self.nw.toggle_calendar()                      # close
        pump(self.app, timeout=0.5)
        self.assertEqual(self.errors, [])
        self.assertIsNone(self.nw.calendar)
        self.assertFalse(self.nw.pad.calendar)

    def test_close_calendar_off(self):
        self._close_calendar_in("off")

    def test_close_calendar_reduced(self):
        self._close_calendar_in("reduced")

    def test_last_note_closes_with_calendar_off(self):
        self.app.set_motion("off")
        self.open_calendar()
        self.app.close_window(self.nw)
        pump(self.app, lambda: self.app.closed, timeout=1.5)
        self.assertTrue(self.app.closed)
        self.assertEqual(self.errors, [])

    # 2. Reduced: the cross-fade's landing must not ride the shared alpha channel
    def test_reduced_view_switch_lands(self):
        self.app.set_motion("reduced")
        cal = self.open_calendar()
        cal.click_view("mini" if cal.expanded else "big")
        pump(self.app, timeout=0.4)                    # the dip, then the switch and its plan
        self.assertTrue(self.settled(), "Motion stayed busy after a view switch in Reduced")
        self.assertEqual(self.errors, [])

    def test_reduced_cancel_mid_crossfade_restores_alpha(self):
        self.app.set_motion("reduced")
        p = self.nw.pad
        self.app.motion.run({p.id: (p.x + 200, p.y, p.x + 200 + p.width, p.y + p.height)})
        pump(self.app, timeout=0.03)                   # fading out
        self.app.motion.cancel([p.id])
        pump(self.app, timeout=0.4)
        self.assertAlmostEqual(float(self.nw.win.attributes("-alpha")), p.alpha, places=2)
        self.assertFalse(self.app.motion.busy())

    # 3. move_to while Motion glides the calendar
    def test_move_to_during_calendar_glide_still_lands(self):
        cal = self.open_calendar()
        b = tuple(cal.target_box)
        ends = []
        self.app.motion.run({"cal": (b[0], b[1] + 60, b[2], b[3] + 60)}, done=lambda: ends.append(1))
        pump(self.app, timeout=0.05)
        cal.move_to(cal.top_box() if hasattr(cal, "top_box") else b)
        self.assertTrue(self.settled(), "Motion never landed the calendar")
        self.assertEqual(ends, [1])

    # 4. closing the calendar starts from where it is, not where a glide last put it
    def test_close_slide_starts_where_it_is(self):
        cal = self.open_calendar()
        b = tuple(cal.target_box)
        moved = (b[0] + 150, b[1] + 90, b[2] + 150, b[3] + 90)
        cal.move_to(moved)                             # (as when it follows its dragged note)
        pump(self.app, timeout=0.1)
        top = cal.top
        self.nw.toggle_calendar()                      # close: slides back toward the note
        pump(self.app, timeout=0.03)                   # its first frames
        x = top.winfo_rootx()
        self.assertLess(abs(x - moved[0]), 30, "the closing slide jumped back to the calendar's old place")

    # 5. the view dip survives its alpha fade being stopped
    def test_dip_switches_even_if_alpha_is_stopped(self):
        cal = self.open_calendar()
        was = cal.expanded
        cal.click_view("mini" if cal.expanded else "big")
        anim.clock_of(cal.top).stop(cal.top, "alpha")  # (as Motion's jump to the other side does)
        pump(self.app, timeout=0.6)
        self.assertFalse(getattr(cal, "_dipping", False))
        self.assertNotEqual(cal.expanded, was)

    # 6. stopping a glide drops its queued move
    def test_stop_drops_queued_move(self):
        clock = self.app.clock
        win = self.nw.win
        x, y = win.winfo_rootx(), win.winfo_rooty()
        w, h = win.winfo_width(), win.winfo_height()
        clock.glide(win, (x + 300, y, x + 300 + w, y + h), 240, frm=(x - 200, y, x - 200 + w, y + h))
        clock.stop(win, "box")                         # the frm write queued a move to x - 200
        win.geometry(f"+{x + 40}+{y}")
        pump(self.app, timeout=0.1)
        self.assertEqual(win.winfo_rootx(), x + 40)

    # 7. no end step when nothing landed (the user took hold in the landing frame)
    def test_no_end_step_after_cancel_in_landing_frame(self):
        p = self.nw.pad
        self.app.motion.run({p.id: (p.x + 120, p.y, p.x + 120 + p.width, p.y + p.height)})
        while self.app.motion.busy() and not self.app.motion._arrived:
            self.app.root.update()
        self.assertTrue(self.app.motion._arrived)
        with patched(self.app, "settle_links", Spy()) as spy:
            self.app.motion.cancel([p.id])
            pump(self.app, timeout=0.1)
        self.assertEqual(spy.call_count, 0)


if __name__ == "__main__":
    unittest.main()
