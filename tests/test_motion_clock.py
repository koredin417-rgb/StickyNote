import tempfile
import time
import unittest
from pathlib import Path

from _support import close_app, make_app, pump


class MotionClockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        pump(self.app, timeout=0.5)
        self.nw = next(iter(self.app.windows.values()))
        p = self.nw.pad
        self.x, self.y, self.w, self.h = p.x, p.y, p.width, p.height

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def box(self, dx):
        return {self.nw.pad.id: (self.x + dx, self.y, self.x + dx + self.w, self.y + self.h)}

    def test_plan_ms_by_distance(self):            # B7: a plan's glide takes longer the further it goes
        import anim
        self.app.apply(self.box(100))
        scale = self.app.px(100) / 100
        self.assertEqual(self.app.motion._items[self.nw.pad.id].ms, anim.glide_ms(100 / scale))

    def test_explicit_ms_kept(self):
        from ui_common import NEW_SLIDE_MS
        self.nw.glide_to(self.x + 300, self.y, ms=NEW_SLIDE_MS)
        self.assertEqual(self.app.motion._items[self.nw.pad.id].ms, 240)

    def test_calendar_close_eases_in(self):         # C4: it visibly tucks back in, then fades
        import anim
        self.nw.toggle_calendar()
        pump(self.app, lambda: self.nw.calendar is not None and not self.app.clock.busy, timeout=2)
        top = self.nw.calendar.top
        self.nw.toggle_calendar()
        for key in ("alpha", "box"):
            a = self.app.clock._anims[(id(top), key)]
            self.assertIs(a.ease, anim.ease_in)
            self.assertEqual(a.ms, 120)

    def test_glide_lands_and_ends_once(self):
        ends = []
        self.app.motion.run(self.box(200), done=lambda: ends.append(1))
        self.assertTrue(self.app.motion.busy())
        pump(self.app, lambda: not self.app.motion.busy(), timeout=1)
        pump(self.app, timeout=0.1)
        self.assertEqual((self.nw.pad.x, ends), (self.x + 200, [1]))
        self.assertEqual(self.nw.win.winfo_rootx(), self.x + 200)

    def test_later_plan_retargets_without_jump(self):
        xs = []
        self.app.motion.run(self.box(300))
        pump(self.app, timeout=0.08)
        self.app.motion.run(self.box(0))                  # turn back mid-glide
        end = time.perf_counter() + 0.5
        while time.perf_counter() < end:
            self.app.root.update()
            xs.append(self.nw.win.winfo_rootx())
            time.sleep(0.002)
        steps = [abs(b - a) for a, b in zip(xs, xs[1:])]
        self.assertLess(max(steps), 40)                   # no frame jumps more than 40 px
        self.assertEqual(self.nw.pad.x, self.x)

    def test_cancel_stops_where_it_is(self):
        self.app.motion.run(self.box(300))
        pump(self.app, timeout=0.08)
        self.app.motion.cancel([self.nw.pad.id])
        x = self.nw.pad.x
        pump(self.app, timeout=0.3)
        self.assertTrue(self.x < x < self.x + 300)
        self.assertEqual(self.nw.pad.x, x)
        self.assertFalse(self.app.motion.busy())

    def test_finish_jumps_to_the_end(self):
        ends = []
        self.app.motion.run(self.box(250), done=lambda: ends.append(1))
        pump(self.app, timeout=0.03)
        self.app.motion.finish()
        self.assertEqual((self.nw.pad.x, ends), (self.x + 250, [1]))

    def test_close_mid_glide_keeps_pad_and_stops(self):
        nw2 = self.app.new_window(from_window=self.nw)
        pump(self.app, timeout=0.6)
        p = nw2.pad
        x0 = p.x
        self.app.motion.run({p.id: (p.x + 300, p.y, p.x + 300 + p.width, p.y + p.height)})
        pump(self.app, timeout=0.06)
        self.app.close_window(nw2)
        pump(self.app, lambda: not self.app.motion.busy(), timeout=1)
        self.assertFalse(self.app.motion.busy())
        self.assertTrue(x0 <= p.x <= x0 + 300)

    def test_glide_holds_fine_timer(self):
        clock = self.app.clock
        pump(self.app, lambda: not clock.busy and not clock.fine_timer_held, timeout=3)
        self.assertFalse(clock.fine_timer_held)          # quiet first (the opening flash is over)
        self.app.motion.run(self.box(200))
        pump(self.app, timeout=0.05)
        self.assertTrue(self.app.clock.fine_timer_held)

    def test_glide_runs_on_the_clock(self):
        self.app.motion.run(self.box(200))
        self.assertTrue(self.app.clock.active(self.nw.win, "box"))


if __name__ == "__main__":
    unittest.main()
