import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
import motion


class MotionPacingTest(unittest.TestCase):
    def test_next_delay_on_grid(self):
        self.assertEqual(motion.next_delay(0.0, 0.020, 15), 10)
        self.assertEqual(motion.next_delay(0.0, 0.031, 15), 14)
        self.assertEqual(motion.next_delay(0.0, 0.0449, 15), 1)
        self.assertEqual(motion.next_delay(0.0, 0.045, 15), 15)


if __name__ == "__main__":
    unittest.main()
