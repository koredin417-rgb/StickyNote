import gc
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump


class GcFreezeTest(unittest.TestCase):
    def test_startup_objects_frozen(self):
        gc.unfreeze()
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d))
            try:
                pump(app, timeout=0.5)
                self.assertGreater(gc.get_freeze_count(), 0)
            finally:
                close_app(app)
                gc.unfreeze()


if __name__ == "__main__":
    unittest.main()
