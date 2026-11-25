import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
import motion
import ui_common


class MotionPacingTest(unittest.TestCase):
    def test_next_delay_on_grid(self):
        self.assertEqual(motion.next_delay(0.0, 0.020, 15), 10)
        self.assertEqual(motion.next_delay(0.0, 0.031, 15), 14)
        self.assertEqual(motion.next_delay(0.0, 0.0449, 15), 1)
        self.assertEqual(motion.next_delay(0.0, 0.045, 15), 15)

    def test_glide_holds_fine_timer(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d))
            try:
                pump(app, lambda: len(app.windows) == 1)
                nw = next(iter(app.windows.values()))
                pump(app, timeout=1.0)                      # the opening fade (which holds the timer) is over
                ui_common._fine_timer["last"] = 0.0
                x, y = nw.pad.x, nw.pad.y
                app.motion.run({nw.pad.id: (x + 200, y, x + 200 + nw.pad.width, y + nw.pad.height)})
                pump(app, timeout=0.05)
                self.assertGreater(ui_common._fine_timer["last"], 0.0)
                pump(app, lambda: not app.motion.busy(), timeout=1)
                self.assertEqual(nw.pad.x, x + 200)
            finally:
                close_app(app)


if __name__ == "__main__":
    unittest.main()
