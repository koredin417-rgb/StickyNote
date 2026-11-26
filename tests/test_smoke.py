import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump


class SmokeTest(unittest.TestCase):
    def test_app_starts_with_one_window_and_quits(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d))
            try:
                self.assertTrue(pump(app, lambda: len(app.windows) == 1))
                self.assertTrue((Path(d) / "notes.json").exists())
            finally:
                close_app(app)
            self.assertTrue(app.closed)


if __name__ == "__main__":
    unittest.main()
