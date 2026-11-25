import random
import unittest

import _support  # noqa: F401  (DPI setup, app path)
from ui_common import fit_text


def measure(s):
    return 7 * len(s)          # every character 7 px


def todays_loop(full, room, measure):
    """The trimming loop _fit_date used before (one measure per character)."""
    text = full
    while text and measure(text + "…") > room:
        text = text[:-1]
    return full if text == full else text.rstrip(" ·") + "…"


class FitTextTest(unittest.TestCase):
    def test_fits_unchanged(self):
        self.assertEqual(fit_text("abc", 28, measure, 7), "abc")

    def test_needs_room_for_ellipsis_like_today(self):
        self.assertEqual(fit_text("abc", 21, measure, 7), "ab…")   # today's rule: full text only if text+… fits

    def test_cut_with_ellipsis(self):
        self.assertEqual(fit_text("abcdefgh", 35, measure, 7), "abcd…")

    def test_strips_separator_before_ellipsis(self):
        self.assertEqual(fit_text("ab · cdef", 35, measure, 7), "ab…")

    def test_no_room_gives_ellipsis_like_today(self):
        self.assertEqual(fit_text("abc", 3, measure, 7), "…")

    def test_empty(self):
        self.assertEqual(fit_text("", 50, measure, 7), "")

    def test_long_text_uses_few_measures(self):
        calls = []
        fit_text("가" * 20000, 700, lambda s: (calls.append(1), 7 * len(s))[1], 7)
        self.assertLess(len(calls), 20)

    def test_same_as_todays_loop(self):
        rng = random.Random(7)
        chars = "abc가나 ·xyz"
        widths = {c: rng.randint(4, 14) for c in chars + "…"}
        var = lambda s: sum(widths[c] for c in s)  # noqa: E731  (uneven widths, like a real font)
        for _ in range(300):
            text = "".join(rng.choice(chars) for _ in range(rng.randint(0, 40)))
            room = rng.randint(0, 300)
            self.assertEqual(fit_text(text, room, var, 4), todays_loop(text, room, var), (text, room))



class FoldedTitleTest(unittest.TestCase):
    def test_folded_long_memo_fits_quickly(self):
        import tempfile
        import time
        from pathlib import Path
        from _support import close_app, make_app, pump
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d))
            try:
                pump(app, lambda: len(app.windows) == 1)
                nw = next(iter(app.windows.values()))
                nw.body.insert("1.0", "가나다라 마바사 " * 2500)          # 20,000 characters on one line
                nw.sync_from_widgets()
                nw.toggle_collapse(instant=True)
                pump(app, timeout=0.5)
                t0 = time.perf_counter()
                nw._fit_date()
                ms = (time.perf_counter() - t0) * 1000
                self.assertTrue(nw.date_label.cget("text").endswith("…"))
                self.assertLess(ms, 50)
            finally:
                close_app(app)


if __name__ == "__main__":
    unittest.main()
