import time
import tkinter as tk
import unittest

import _support  # noqa: F401  (DPI setup, app path)
import anim
import winapi


class DeadlineTest(unittest.TestCase):
    def test_vblank_target(self):
        # vblank at 1.000, period 13.9 ms; now 1.010 -> first vblank >= 1.014 is 1.0278 -> minus 2 ms
        self.assertAlmostEqual(anim.next_deadline(1.010, 1.000, 0.0139), 1.0258, places=4)

    def test_every_second_vblank(self):
        self.assertAlmostEqual(anim.next_deadline(1.010, 1.000, 0.0069, every=2), 1.0256, places=4)

    def test_grid_fallback(self):
        self.assertAlmostEqual(anim.next_deadline(0.020, 0.0, 1 / 60), 1 / 30 - 0.002, places=4)


class ClockTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.clock = anim.install(self.root)

    def tearDown(self):
        self.clock.close()
        self.root.destroy()

    def run_for(self, s):
        end = time.perf_counter() + s
        while time.perf_counter() < end:
            self.root.update()
            time.sleep(0.001)

    def test_animate_runs_to_done(self):
        ks, done = [], []
        self.clock.animate(self.root, "x", 120, ks.append, lambda: done.append(1))
        self.run_for(0.3)
        self.assertEqual(ks[-1], 1.0)
        self.assertEqual(done, [1])
        self.assertTrue(all(a <= b for a, b in zip(ks, ks[1:])))

    def test_same_key_replaces_without_old_done(self):
        done = []
        self.clock.animate(self.root, "x", 200, lambda k: None, lambda: done.append("old"))
        self.clock.animate(self.root, "x", 50, lambda k: None, lambda: done.append("new"))
        self.run_for(0.3)
        self.assertEqual(done, ["new"])

    def test_tcl_error_in_step_drops_silently(self):
        done = []

        def bad(k):
            raise tk.TclError("gone")
        self.clock.animate(self.root, "x", 50, bad, lambda: done.append(1))
        self.run_for(0.15)
        self.assertEqual(done, [])
        self.assertFalse(self.clock.active(self.root, "x"))

    def test_request_coalesces(self):
        n = []
        f = lambda: n.append(1)  # noqa: E731
        self.clock.request(f)
        self.clock.request(f)
        self.run_for(0.05)
        self.assertEqual(n, [1])

    def test_tween_retargets_from_current_value(self):
        box = {"v": 0.0}
        rd, wr = (lambda: box["v"]), (lambda v: box.__setitem__("v", v))
        self.clock.tween(self.root, "c", 100.0, 240, read=rd, write=wr)
        self.run_for(0.08)
        mid = box["v"]
        self.assertTrue(0 < mid < 100)
        seen = []
        self.clock.tween(self.root, "c", 0.0, 240, read=rd, write=lambda v: (seen.append(v), wr(v)))
        self.run_for(0.35)
        self.assertAlmostEqual(seen[0], mid, delta=15)      # continues from where it was, no snap
        self.assertEqual(box["v"], 0.0)

    def test_tween_tuple_values(self):
        box = {"v": (0.0, 0.0)}
        self.clock.tween(self.root, "p", (10.0, 20.0), 60, read=lambda: box["v"],
                         write=lambda v: box.__setitem__("v", v))
        self.run_for(0.2)
        self.assertEqual(box["v"], (10.0, 20.0))

    def test_stop_keeps_current_value_no_done(self):
        box, done = {"v": 0.0}, []
        self.clock.tween(self.root, "c", 100.0, 240, read=lambda: box["v"],
                         write=lambda v: box.__setitem__("v", v), done=lambda: done.append(1))
        self.run_for(0.08)
        self.clock.stop(self.root, "c")
        v = box["v"]
        self.run_for(0.3)
        self.assertEqual((box["v"], done), (v, []))

    def test_frames_on_display_period(self):
        t = []
        self.clock.animate(self.root, "p", 600, lambda k: t.append(time.perf_counter()))
        self.run_for(0.7)
        iv = sorted((b - a) * 1000 for a, b in zip(t, t[1:]))
        period = winapi.composition_timing()[1] * 1000
        self.assertLess(abs(iv[len(iv) // 2] - period), 2.0)

    def test_fine_timer_held_while_active(self):
        self.clock.animate(self.root, "x", 200, lambda k: None)
        self.run_for(0.05)
        self.assertTrue(self.clock.fine_timer_held)
        self.run_for(0.9)
        self.assertFalse(self.clock.fine_timer_held)

    def test_idle_runs_after_quiet(self):
        n = []
        self.clock.idle(lambda: n.append(1))
        self.run_for(0.5)
        self.assertEqual(n, [])
        self.run_for(0.8)
        self.assertEqual(n, [1])

    def test_close_cancels_everything(self):
        self.clock.animate(self.root, "x", 500, lambda k: None)
        self.run_for(0.05)
        self.clock.close()
        self.assertFalse(self.clock.busy)
        self.assertFalse(self.clock.fine_timer_held)
        self.assertEqual((self.clock._job, self.clock._idle_job, self.clock._fine_job), (None, None, None))

    def test_nothing_scheduled_at_rest(self):
        self.clock.animate(self.root, "x", 50, lambda k: None)
        self.run_for(0.8)
        self.assertFalse(self.clock.busy)

    def test_perf_counts_one_frame_per_key_per_tick(self):
        import perf
        old, perf.ENABLED = perf.ENABLED, True
        perf.perf.reset()
        try:
            for i in range(3):                          # three windows gliding: one "box" frame per tick
                self.clock.animate(object.__new__(type("W%d" % i, (), {})), "box", 200, lambda k: None)
            self.run_for(0.3)
            f = perf.perf.report()["frames"]["box"]
            self.assertGreater(f["p50"], 5.0)
        finally:
            perf.ENABLED = old
            perf.perf.reset()


def _lin(t):
    return t


class FirstFrameTest(unittest.TestCase):
    """B1: an animation's clock starts at its first frame, not at the call (work done between the
    call and the first frame must not eat into the curve)."""
    setUp, tearDown, run_for = ClockTest.setUp, ClockTest.tearDown, ClockTest.run_for

    def test_first_frame_starts_one_period_in(self):
        P, ks = self.clock._period(), []
        self.clock.animate(self.root, "x", 120, ks.append, ease=_lin)
        time.sleep(0.06)                        # the caller's other work before the first frame
        self.run_for(0.3)
        self.assertEqual(ks[0], 0.0)
        self.assertGreater(ks[1], 0.0)
        self.assertLessEqual(ks[1], 1.6 * P / 0.120)
        self.assertEqual(ks[-1], 1.0)

    def test_tween_first_frame_one_period_in(self):
        P, vals = self.clock._period(), []
        self.clock.tween(self.root, "c", 100.0, 120, frm=0.0, ease=_lin, read=lambda: 0.0, write=vals.append)
        time.sleep(0.06)
        self.run_for(0.3)
        self.assertEqual(vals[0], 0.0)
        self.assertGreater(vals[1], 0.0)
        self.assertLessEqual(vals[1], 100 * 1.6 * P / 0.120)

    def test_stop_before_first_frame_stays(self):
        vals = []
        self.clock.tween(self.root, "c", 100.0, 120, frm=0.0, read=lambda: 0.0, write=vals.append)
        self.clock.stop(self.root, "c")
        self.run_for(0.1)
        self.assertEqual(vals, [0.0])

    def test_wake_takes_fine_timer(self):
        self.clock.animate(self.root, "x", 30, lambda k: None)
        self.run_for(0.15)
        self.assertFalse(self.clock.busy)
        self.clock._release_fine()
        self.assertFalse(self.clock.fine_timer_held)
        self.clock.request(lambda: None)
        self.assertTrue(self.clock.fine_timer_held)


class VelocityTest(unittest.TestCase):
    """Phase 8, B8: a tween can start at a given speed (a thrown note's drop glide)."""
    setUp, tearDown = ClockTest.setUp, ClockTest.tearDown

    def test_tween_velocity_start_slope(self):
        rw = dict(read=lambda: 0.0, write=lambda v: None)
        self.clock.tween(self.root, "c", 100.0, 200, frm=0.0, velocity=(1000.0,), **rw)
        self.assertEqual(self.clock._anims[(id(self.root), "c")].m[0], anim.start_slope(0, 100, 1000, 0.2))
        self.assertEqual(self.clock._anims[(id(self.root), "c")].m[0], 200)
        self.clock.tween(self.root, "d", 100.0, 200, frm=0.0, **rw)
        self.assertEqual(self.clock._anims[(id(self.root), "d")].m[0], 300)


class HalfRateTest(unittest.TestCase):
    """B2: every second vblank only under sustained load: the median of the last 6 ticks' work,
    entering above 0.8 x period and leaving below 0.55 x; done callbacks and an animation's
    first tick are not counted; going idle forgets it all."""
    setUp, tearDown, run_for = ClockTest.setUp, ClockTest.tearDown, ClockTest.run_for
    P = 0.0139

    def test_hysteresis(self):
        c = self.clock
        c._work = [0.012] * 6
        self.assertEqual(c._every(self.P), 2)
        c._work = [0.009] * 6
        self.assertEqual(c._every(self.P), 2)       # between the two lines: stays
        c._work = [0.007] * 6
        self.assertEqual(c._every(self.P), 1)
        c._work = [0.012] * 5
        self.assertEqual(c._every(self.P), 1)       # too few to say, from rest
        c._work = [0.02] * 6
        self.assertEqual(c._every(0.0167), 1)       # a 60 Hz display is never halved

    def test_one_heavy_tick_does_not_halve(self):
        self.clock._work = [0.002] * 5 + [0.05]
        self.assertEqual(self.clock._every(self.P), 1)

    def test_idle_clears_work(self):
        c = self.clock
        c._work, c._half = [0.02] * 6, True
        c.animate(self.root, "x", 30, lambda k: None)
        self.run_for(0.3)
        self.assertEqual((c._work, c._half), ([], False))

    def test_done_not_counted(self):
        c = self.clock
        c.animate(self.root, "light", 300, lambda k: None)
        c.animate(self.root, "short", 30, lambda k: None, lambda: time.sleep(0.025))
        self.run_for(0.15)
        self.assertTrue(c._work)
        self.assertLess(max(c._work), 0.010)

    def test_first_tick_not_counted(self):
        c, calls = self.clock, []
        c.animate(self.root, "light", 300, lambda k: None)
        self.run_for(0.05)

        def heavy_first_tick(k):
            calls.append(k)
            if len(calls) == 2:                     # (call 1 is the start step, inside animate)
                time.sleep(0.025)
        c.animate(self.root, "new", 200, heavy_first_tick)
        self.run_for(0.1)
        self.assertGreater(len(calls), 2)
        self.assertLess(max(c._work), 0.010)


if __name__ == "__main__":
    unittest.main()
