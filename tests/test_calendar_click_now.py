"""2026-11-28 (the user: "the click -> highlight is just slow"): a click highlights the day at once;
only opening that day's list waits for DOUBLE_CLICK_MS (a double-click makes a memo on that day)."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump


class ClickNowTest(unittest.TestCase):
    def test_highlight_at_once(self):
        tmp = tempfile.TemporaryDirectory()
        app = make_app(Path(tmp.name))
        try:
            pump(app, lambda: len(app.windows) == 1)
            nw = next(iter(app.windows.values()))
            nw.toggle_calendar()
            pump(app, timeout=1.0)
            cal = nw.calendar
            g = cal.grid
            iso = sorted(cal._spots)[10]
            cx, cy, _tw, _th = cal._spots[iso]
            g.event_generate("<ButtonPress-1>", x=int(cx), y=int(cy))
            g.event_generate("<ButtonRelease-1>", x=int(cx), y=int(cy))
            pump(app, timeout=0.02)                        # well before DOUBLE_CLICK_MS
            self.assertEqual(cal.selected, iso)
            self.assertTrue(g.find_withtag("selected"))
            self.assertEqual(nw.view, "home")              # (the list waits: it may be a double-click)
            pump(app, timeout=0.5)
            self.assertEqual(nw.view, "list")
        finally:
            close_app(app)
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
