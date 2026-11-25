"""Phase 4: drag and resize do one unit of work per display frame, through the window batch."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import winapi
from _support import Spy, close_app, make_app, patched, pump

ALT = 0x20000


def ev(x, y, state=0):
    return SimpleNamespace(x_root=int(x), y_root=int(y), x=0, y=0, widget=None, state=state)


class InteractTest(unittest.TestCase):
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
        pump(self.app, lambda: not self.app.motion.busy(), timeout=2)
        pump(self.app, timeout=t)

    def group_of_three(self):
        a = self.nw
        b = self.app.new_window(a)
        self.settle()
        c = self.app.new_window(b)
        self.settle()
        self.assertGreaterEqual(len(self.app.group_windows(a.pad.id)), 3)
        return a, b, c

    def frame(self):
        """Run the event loop until the clock has done its next frame."""
        clock = self.app.clock
        pump(self.app, lambda: not clock._requests and not clock._moves, timeout=0.5)

    # ---- Task 1
    def test_one_apply_per_frame(self):
        nw = self.nw
        x, y = nw.pad.x + 60, nw.pad.y + 10
        nw._drag_start(ev(x, y))
        with patched(self.app, "snap", Spy(wraps=self.app.snap)) as spy:
            nw._drag_move(ev(x + 10, y))
            nw._drag_move(ev(x + 20, y))
            nw._drag_move(ev(x + 30, y + 5))
            self.assertEqual(spy.call_count, 0)        # nothing until the frame
            self.frame()
            self.assertEqual(spy.call_count, 1)
        self.assertEqual(nw._drag_pt, (x + 30, y + 5))
        nw._drag_end(ev(x + 30, y + 5))
        self.settle()

    def test_group_moves_in_one_batch(self):
        a, b, c = self.group_of_three()
        x, y = a.pad.x + 60, a.pad.y + 10
        a._drag_start(ev(x, y))
        with patched(winapi, "defer_move", Spy(wraps=winapi.defer_move)) as spy:
            a._drag_move(ev(x + 15, y + 9))
            self.frame()
        hwnds = {winapi.hwnd_of(w.win) for w in self.app.group_windows(a.pad.id)}
        self.assertEqual(spy.call_count, 1)
        moved = {m[0] for m in spy.calls[0][0][0]}
        self.assertTrue(hwnds <= moved, (hwnds, moved))
        a._drag_end(ev(x + 15, y + 9))
        self.settle()

    def test_release_flushes_latest_pointer(self):
        nw = self.nw
        x0, y0 = nw.pad.x, nw.pad.y
        x, y = x0 + 60, y0 + 10
        nw._drag_start(ev(x, y, ALT))
        nw._drag_move(ev(x + 40, y + 30, ALT))
        nw._drag_move(ev(x + 80, y + 60, ALT))
        nw._drag_end(ev(x + 80, y + 60, ALT))          # let go before the frame
        self.settle()
        self.assertEqual((nw.pad.x, nw.pad.y), (x0 + 80, y0 + 60))

    def test_resize_one_plan_per_frame(self):
        nw = self.nw
        g = nw.grip
        x, y = g.winfo_rootx() + 2, g.winfo_rooty() + 2
        w0 = nw.win.winfo_width()
        nw._resize_start(ev(x, y, ALT))
        with patched(self.app, "plan_resize", Spy(wraps=self.app.plan_resize)) as spy:
            nw._resize_move(ev(x + 10, y + 4, ALT))
            nw._resize_move(ev(x + 20, y + 8, ALT))
            nw._resize_move(ev(x + 30, y + 12, ALT))
            self.assertEqual(spy.call_count, 0)
            self.frame()
            self.assertEqual(spy.call_count, 1)
        pump(self.app, timeout=0.1)
        self.assertEqual(nw.win.winfo_width(), w0 + 30)
        nw._drag_end(ev(x + 30, y + 12, ALT))
        self.settle()

    def test_live_plan_matches_per_event(self):
        a, b, c = self.group_of_three()
        g = a.grip
        x, y = g.winfo_rootx() + 2, g.winfo_rooty() + 2
        a._resize_start(ev(x, y, ALT))                  # a alone: the notes in line are pushed live
        for k in range(1, 6):
            a._resize_move(ev(x + 25 * k, y + 15 * k, ALT))
            if k % 2:
                self.frame()
        self.frame()
        final = a._now[a.pad.id]                        # the box the drag put it at
        plan = self.app.plan_resize({a.pad.id: tuple(final)}, a._resize_shapes)
        self.assertTrue(len(a._now) > 1, "nothing was pushed: the test does not test")
        for sid, box in a._now.items():
            if sid != a.pad.id:
                self.assertEqual(tuple(box), tuple(plan.boxes[sid]))
        a._drag_end(ev(x + 125, y + 75, ALT))
        self.settle()


class QuietGestureTest(InteractTest):
    """Task 2: while a gesture runs, notes skip the save and layout work their <Configure> does."""

    def test_one_apply_per_frame(self):            # (the parent's tests run once, in InteractTest)
        pass

    test_group_moves_in_one_batch = test_release_flushes_latest_pointer = test_one_apply_per_frame
    test_resize_one_plan_per_frame = test_live_plan_matches_per_event = test_one_apply_per_frame

    def test_frozen_note_lays_out_once(self):
        a, b, c = self.group_of_three()
        g = a.grip
        x, y = g.winfo_rootx() + 2, g.winfo_rooty() + 2
        spies = {}
        a._resize_start(ev(x, y))
        for o in (b, c):
            spies[o] = Spy(wraps=o._arrange_chrome)
            o._arrange_chrome = spies[o]
        frozen = set()
        for k in range(1, 5):
            a._resize_move(ev(x - 12 * k, y - 8 * k))
            self.frame()
            frozen |= {o for o in (b, c) if o._cover is not None}
        self.assertTrue(frozen, "no note was frozen: the test does not test")
        for o in frozen:
            self.assertEqual(spies[o].call_count, 0)
        a._drag_end(ev(x - 48, y - 32))
        self.settle()
        for o in frozen:
            self.assertGreaterEqual(spies[o].call_count, 1)
            last = o.rail_shown()[-1]
            self.assertLessEqual(last.winfo_rooty() + last.winfo_height(), o.btn_more.winfo_rooty())

    def test_docked_calendar_follows_drag(self):
        a = self.nw
        a.toggle_calendar()
        self.settle()
        cal = a.calendar
        x, y = a.pad.x + 60, a.pad.y + 10
        a._drag_start(ev(x, y, ALT))
        for k in range(1, 4):
            nx0 = a.pad.x
            c0 = tuple(cal.target_box)
            a._drag_move(ev(x - 20 * k, y + 10 * k, ALT))
            self.frame()
            pump(self.app, timeout=0.05)
            shift = a.pad.x - nx0
            self.assertNotEqual(shift, 0)
            self.assertEqual(cal.target_box[0] - c0[0], shift)
        a._drag_end(ev(x - 60, y + 30, ALT))
        self.settle()

    def test_no_save_mid_gesture(self):
        a, b, c = self.group_of_three()
        x, y = a.pad.x + 60, a.pad.y + 10
        a._drag_start(ev(x, y))
        with patched(self.app, "request_save", Spy(wraps=self.app.request_save)) as spy:
            for k in range(1, 4):
                a._drag_move(ev(x + 10 * k, y + 6 * k))
                self.frame()
                pump(self.app, timeout=0.03)
            self.assertEqual(spy.call_count, 0)
            a._drag_end(ev(x + 30, y + 18))
            self.settle()
            self.assertGreaterEqual(spy.call_count, 1)


if __name__ == "__main__":
    unittest.main()
