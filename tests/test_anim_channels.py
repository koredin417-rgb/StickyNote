import tempfile
import time
import unittest
from pathlib import Path

from _support import close_app, make_app, pump


class ChannelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        pump(self.app, timeout=0.5)
        self.nw = next(iter(self.app.windows.values()))

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def test_fast_paging_never_jumps(self):
        self.nw.toggle_calendar()
        pump(self.app, timeout=0.5)
        cal = self.nw.calendar
        g = cal.grid

        def fifteens():                                # each month on the canvas has one "15"
            return sorted(g.coords(i)[0] for i in g.find_all()
                          if g.type(i) == "text" and g.itemcget(i, "text") == "15")
        rest = fifteens()[0]
        cal.next_month()
        pump(self.app, timeout=0.06)
        incoming = fifteens()[-1]                      # the month sliding in, part way
        self.assertGreater(incoming - rest, 5)
        cal.next_month()                               # second click mid-slide
        self.assertTrue(any(abs(x - incoming) < 3 for x in fifteens()),
                        "the month sliding in jumped when the next click came")
        pump(self.app, timeout=0.8)
        self.assertEqual(g.find_withtag("paging"), ())
        self.assertEqual(len(fifteens()), 1)
        landed = fifteens()
        cal.draw()                                     # a fresh page of the same month: at rest
        self.assertEqual(fifteens(), landed)
        y, m = cal.month
        self.assertEqual(m, ((time.localtime().tm_mon + 1) % 12) + 1)

    def test_settings_reverse_mid_slide(self):
        self.nw.toggle_settings()
        pump(self.app, timeout=0.3)
        sv = self.nw.settings_view
        key = next(iter(sv.list_rows))
        sv.open(key)
        pump(self.app, timeout=0.08)
        x_mid = float(sv.detail_area.canvas.place_info()["relx"])
        sv.close()
        pump(self.app, timeout=0.02)
        x_now = float(sv.detail_area.canvas.place_info()["relx"])
        self.assertLess(abs(x_now - x_mid), 0.2)       # turned back from where it was, no snap to 0
        pump(self.app, timeout=0.4)
        self.assertEqual(sv.opened, None)

    def test_calendar_open_close_fast_ends_closed(self):
        self.nw.toggle_calendar()
        pump(self.app, timeout=0.05)
        self.nw.toggle_calendar()
        pump(self.app, timeout=0.5)
        self.assertIsNone(self.nw.calendar)


if __name__ == "__main__":
    unittest.main()
