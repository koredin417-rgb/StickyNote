import unittest

import _support  # noqa: F401  (DPI setup, app path)
import anim


class CurvesTest(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual((anim.FAST, anim.BASE, anim.LONG), (120, 180, 240))
        self.assertEqual((anim.exit_ms(120), anim.exit_ms(180)), (80, 120))

    def test_hermite_with_normal_slope_is_ease_out_cubic(self):
        for s in (0, .1, .25, .5, .8, 1):
            self.assertAlmostEqual(anim.hermite(10, 110, 300, s), 10 + 100 * anim.ease_out(s))

    def test_hermite_ends(self):
        self.assertEqual(anim.hermite(5, 9, 40, 0), 5)
        self.assertEqual(anim.hermite(5, 9, 40, 1), 9)
        self.assertAlmostEqual(anim.hermite_slope(5, 9, 40, 1), 0)
        self.assertAlmostEqual(anim.hermite_slope(5, 9, 40, 0), 40)

    def test_reversal_turns_smoothly(self):        # moving +200/s, told to go back to 0 from 100
        m = anim.start_slope(100, 0, velocity=200, duration_s=0.24)
        self.assertGreater(m, 0)                   # keeps going forward briefly
        vals = [anim.hermite(100, 0, m, i / 20) for i in range(21)]
        self.assertGreater(max(vals), 100)         # turns after a small overshoot
        self.assertEqual(vals[-1], 0)

    def test_slope_capped(self):
        self.assertEqual(anim.start_slope(0, 10, velocity=1e6, duration_s=0.24), 1.5 * 30)

    def test_zero_velocity_is_normal(self):
        self.assertEqual(anim.start_slope(0, 10, 0, 0.24), 30)

    def test_ease_in(self):
        self.assertEqual((anim.ease_in(0), anim.ease_in(0.5), anim.ease_in(1)), (0, 0.25, 1))


if __name__ == "__main__":
    unittest.main()
