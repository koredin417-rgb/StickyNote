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

    def test_group_freezes_at_press(self):
        a, b, c = self.group_of_three()
        g = a.grip
        x, y = g.winfo_rootx() + 2, g.winfo_rooty() + 2
        a._resize_start(ev(x, y))
        a0, b0, a1, b1 = a._resize_box
        for o in (b, c):
            l, t, r, bt = o.pad.x, o.pad.y, o.pad.x + o.pad.width, o.pad.y + o.pad.height
            in_line = min(r, a1) - max(l, a0) > 0 or min(bt, b1) - max(t, b0) > 0
            self.assertEqual(o._cover is not None, in_line, o.pad.id)
        a._drag_end(ev(x, y))
        self.settle()
        for o in (a, b, c):
            self.assertIsNone(o._cover)

    def test_solo_resize_makes_its_outline_window_at_press(self):
        nw = self.nw
        self.app._outlines = None
        g = nw.grip
        x, y = g.winfo_rootx() + 2, g.winfo_rooty() + 2
        nw._resize_start(ev(x, y, ALT))
        self.assertIsNotNone(self.app._outlines)        # built now, not inside the first frame
        nw._drag_end(ev(x, y, ALT))
        self.settle()

    def test_ring_window_keeps_its_size_while_growing(self):
        ring = self.app.ring
        px = self.app.px
        boxes = [(100, 100, 420, 420), (430, 100, 750, 420)]
        ring.show(boxes, self.nw.win)
        pump(self.app, timeout=0.1)
        with patched(ring.top, "geometry", Spy(wraps=ring.top.geometry)) as spy:
            for k in range(1, 11):              # the first box grows 3 px a frame, as in a resize
                grown = [(100, 100, 420 + 3 * k, 420 + 2 * k), (430 + 3 * k, 100, 750 + 3 * k, 420 + 2 * k)]
                ring.move(grown)
                pump(self.app, timeout=0.01)
        self.assertLessEqual(spy.call_count, 1)
        x0, y0 = ring.top.winfo_rootx(), ring.top.winfo_rooty()
        x1, y1 = x0 + ring.top.winfo_width(), y0 + ring.top.winfo_height()
        gap, _r, lw = (px(v) for v in (6, 9, 2))
        self.assertLessEqual(x0, 100 - gap - lw)
        self.assertGreaterEqual(x1, 780 + gap + lw)
        self.assertGreaterEqual(y1, 440 + gap + lw)
        ring.hide()

    def test_ring_moves_without_redrawing_on_a_drag(self):
        ring = self.app.ring
        boxes = [(100, 100, 420, 420), (430, 100, 750, 420)]
        ring.show(boxes, self.nw.win)
        pump(self.app, timeout=0.1)
        with patched(ring.cv, "delete", Spy(wraps=ring.cv.delete)) as spy:
            for k in range(1, 11):              # the same outline, moved 7 px a frame
                ring.move([(a + 7 * k, b + 3 * k, c + 7 * k, d + 3 * k) for a, b, c, d in boxes])
                pump(self.app, timeout=0.01)
        self.assertEqual(spy.call_count, 0)
        self.assertEqual(ring.top.winfo_rootx() - ring._frame[0], 0)
        ring.hide()

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


class PerFrameTest(InteractTest):
    """Task 6: picture pan / zoom, the calendar's grip and its range drag, once per frame."""

    test_one_apply_per_frame = QuietGestureTest.test_one_apply_per_frame
    test_group_moves_in_one_batch = test_release_flushes_latest_pointer = test_one_apply_per_frame
    test_resize_one_plan_per_frame = test_live_plan_matches_per_event = test_one_apply_per_frame

    def test_picture_pan_renders_once_per_frame(self):
        from PIL import Image
        nw = self.nw
        nw.set_style("image")
        nw.add_image(Image.new("RGB", (1600, 1200), "#3366AA"))
        self.settle()
        v = nw.viewer
        v.zoom_at(40, 40, 3.0)
        self.frame()
        v._press(SimpleNamespace(x=60, y=60))
        with patched(v, "_draw_picture", Spy(wraps=v._draw_picture)) as spy:
            for k in range(1, 4):
                v._move(SimpleNamespace(x=60 - 10 * k, y=60 - 6 * k))
            self.assertEqual(spy.call_count, 0)
            self.frame()
            self.assertEqual(spy.call_count, 1)
            for k in range(3):
                v.zoom_at(50, 50, 1.2)
            self.frame()
            self.assertEqual(spy.call_count, 2)

    def open_big_calendar(self):
        self.nw.toggle_calendar()
        self.settle()
        cal = self.nw.calendar
        cal.click_view("big")
        self.settle(0.6)
        return cal

    def test_calendar_grip_draws_once_per_frame(self):
        cal = self.open_big_calendar()
        g = cal.grip
        x, y = g.winfo_rootx() + 2, g.winfo_rooty() + 2
        cal._resize_start(ev(x, y))
        with patched(cal, "draw", Spy(wraps=cal.draw)) as spy:
            for k in range(1, 4):
                cal._resize_move(ev(x + 8 * k, y + 5 * k))
            self.assertEqual(spy.call_count, 0)
            self.frame()
            self.assertEqual(spy.call_count, 1)
        cal._resize_end(ev(x + 24, y + 15))
        self.settle()

    def test_range_card_only_on_change(self):
        import ui_calendar
        cal = self.open_big_calendar()
        cells = [c for c in cal._cells if c[4].month == cal.month[1]]
        a, b, c = cells[8], cells[9], cells[10]
        cal._chip_drag = {"note": None, "day": a[4], "moving": False}

        def at(cell, dx):
            x, y = cell[0] + dx, cell[1] + 10
            return SimpleNamespace(x=x, y=y, x_root=cal.grid.winfo_rootx() + x, y_root=cal.grid.winfo_rooty() + y)
        with patched(ui_calendar, "_rounded_card", Spy(wraps=ui_calendar._rounded_card)) as spy:
            cal._range_move(at(b, 5))
            cal._range_move(at(b, 25))                  # the same days: the card only moves
            self.assertEqual(spy.call_count, 1)
            cal._range_move(at(c, 5))
            self.assertEqual(spy.call_count, 2)
        cal._hide_count()
        cal.grid.delete("ghost")
        cal._chip_drag = None



class GroupResizeClipTest(unittest.TestCase):
    """Phase 8, B3: in a group resize the frozen notes' windows keep their size (each real resize
    costs Tk a layout and a repaint); a window region shows the size the drag gives them, and
    the window grows only in RING_SLACK steps. Let go, each is exactly its pad's box again."""
    setUp, tearDown, settle, frame = InteractTest.setUp, InteractTest.tearDown, InteractTest.settle, InteractTest.frame
    group_of_three = InteractTest.group_of_three

    def start(self):
        a, b, c = self.group_of_three()
        g = a.grip
        x, y = g.winfo_rootx() + 2, g.winfo_rooty() + 2
        a._resize_start(ev(x, y))
        frozen = [o for o in (b, c) if o._cover is not None]
        self.assertTrue(frozen, "no note in line: the test does not test")
        return a, (b, c), frozen, x, y

    def test_group_resize_shrink_keeps_window_size(self):
        a, others, frozen, x, y = self.start()
        sizes = {o: (o.win.winfo_width(), o.win.winfo_height()) for o in frozen}
        shown0 = {o: (o.pad.width, o.pad.height) for o in frozen}
        for k in range(1, 6):
            a._resize_move(ev(x - 4 * k, y - 4 * k))
            self.frame()
        pump(self.app, timeout=0.05)
        for o in frozen:
            self.assertEqual((o.win.winfo_width(), o.win.winfo_height()), sizes[o])
            self.assertIsNotNone(o._clip)
            self.assertNotEqual(tuple(o._clip[2:]), shown0[o])     # (it shows a smaller size)
        a._drag_end(ev(x - 20, y - 20))
        self.settle()

    def test_group_resize_grow_steps_by_slack(self):
        a, others, frozen, x, y = self.start()
        seen = {o: [(o.win.winfo_width(), o.win.winfo_height())] for o in frozen}
        for k in range(1, 16):
            a._resize_move(ev(x + 10 * k, y + 10 * k))
            self.frame()
            pump(self.app, timeout=0.01)
            for o in frozen:
                size = (o.win.winfo_width(), o.win.winfo_height())
                if size != seen[o][-1]:
                    seen[o].append(size)
        for o in frozen:
            self.assertLessEqual(len(seen[o]) - 1, 2, seen[o])
        a._drag_end(ev(x + 150, y + 150))
        self.settle()

    def test_dwm_border_hidden_while_clipped(self):
        # DWM draws a window's 1 px border at its real size even outside its region: hidden
        # while a region shows less than the window, back when the region goes
        calls = []
        with patched(winapi, "_dwm_border", lambda hwnd, on: calls.append(on)):
            a, others, frozen, x, y = self.start()
            for k in range(1, 4):
                a._resize_move(ev(x - 4 * k, y - 4 * k))
                self.frame()
            self.assertIn(False, calls)
            self.assertNotIn(True, calls)
            a._drag_end(ev(x - 12, y - 12))
            self.settle()
        self.assertEqual(calls.count(True), len(frozen))
        self.assertEqual(calls[-1], True)

    def test_group_resize_release_exact(self):
        a, b, c = self.group_of_three()
        c.toggle_collapse(instant=True)             # a folded member keeps its folded height
        self.settle()
        g = a.grip
        x, y = g.winfo_rootx() + 2, g.winfo_rooty() + 2
        a._resize_start(ev(x, y))
        for k in range(1, 6):
            a._resize_move(ev(x - 4 * k, y - 4 * k))
            self.frame()
        a._drag_end(ev(x - 20, y - 20))
        self.app.root.update_idletasks()
        from geom import shown_h
        for o in (a, b, c):                         # the size at once (no frame at the window's big size)
            self.assertEqual((o.win.winfo_width(), o.win.winfo_height()), (o.pad.width, shown_h(o.pad)), o.pad.id)
        self.settle()
        for o in (a, b, c):
            p = o.pad
            self.assertEqual((o.win.winfo_rootx(), o.win.winfo_rooty(), o.win.winfo_width(), o.win.winfo_height()),
                             (p.x, p.y, p.width, shown_h(p)), p.id)
            self.assertIsNone(getattr(o, "_clip", None))
            self.assertIsNone(o._cover)
        self.assertTrue(c.pad.collapsed)


if __name__ == "__main__":
    unittest.main()
