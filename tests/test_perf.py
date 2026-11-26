import gc
import time
import unittest

import _support  # noqa: F401  (DPI setup, app path)
import perf


class PerfTest(unittest.TestCase):
    def test_frame_intervals(self):
        p = perf.Perf()
        for t in (0.000, 0.016, 0.032, 0.063, 1.000, 1.016):   # 1.000 starts a new run (gap > 250 ms)
            p.frame("glide", t)
        f = p.report()["frames"]["glide"]
        self.assertEqual(f["n"], 4)
        self.assertAlmostEqual(f["max"], 31.0, places=3)
        self.assertAlmostEqual(f["p50"], 16.0, places=3)

    def test_span_records_ms(self):
        p = perf.Perf()
        with p.span("save"):
            time.sleep(0.02)
        s = p.report()["spans"]["save"]
        self.assertEqual(s["n"], 1)
        self.assertGreaterEqual(s["max"], 15.0)

    def test_sample_reads_process(self):
        s = perf.Perf().sample()
        self.assertGreater(s["private_bytes"], 1_000_000)
        self.assertGreaterEqual(s["gdi"], 0)
        self.assertGreaterEqual(s["user"], 0)

    def test_live_windows_drop_when_collected(self):
        class W:
            pass
        p, w = perf.Perf(), W()
        p.track_window(w)
        self.assertEqual(p.live_windows(), 1)
        del w
        gc.collect()
        self.assertEqual(p.live_windows(), 0)

    def test_reset_clears(self):
        p = perf.Perf()
        p.frame("a", 0.0)
        p.frame("a", 0.016)
        p.reset()
        self.assertEqual(p.report(), {"frames": {}, "spans": {}})

    def test_timed_records_when_enabled(self):
        p = perf.Perf()
        f = perf.timed("work", enabled=True, into=p)(lambda x: x * 2)
        self.assertEqual(f(21), 42)
        self.assertEqual(p.report()["spans"]["work"]["n"], 1)

    def test_timed_is_identity_when_disabled(self):
        fn = lambda: 1  # noqa: E731
        self.assertIs(perf.timed("work", enabled=False)(fn), fn)


if __name__ == "__main__":
    unittest.main()
