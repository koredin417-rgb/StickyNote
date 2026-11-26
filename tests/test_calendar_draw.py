import tempfile
import unittest
from pathlib import Path
from _support import Spy, close_app, make_app, pump, patched


class CalendarDrawTest(unittest.TestCase):
    def test_draw_does_not_compute_marked_days(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d))
            try:
                pump(app, lambda: len(app.windows) == 1)
                nw = next(iter(app.windows.values()))
                nw.toggle_calendar()
                pump(app, lambda: nw.calendar is not None, timeout=1)
                with patched(type(nw.calendar), "marked_days", Spy(raises=AssertionError("called"))):
                    nw.calendar.draw()
            finally:
                close_app(app)


if __name__ == "__main__":
    unittest.main()
