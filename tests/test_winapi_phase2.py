import time
import tkinter as tk
import unittest

import _support  # noqa: F401  (DPI setup, app path)
import winapi


class WinapiPhase2Test(unittest.TestCase):
    def test_composition_timing(self):
        t = winapi.composition_timing()
        self.assertIsNotNone(t)
        vblank, period = t
        self.assertTrue(0.004 < period < 0.05)                         # 20-250 Hz
        self.assertLess(abs(time.perf_counter() - vblank), 1.0)        # a recent vblank, same clock

    def test_defer_move_moves_both(self):
        root = tk.Tk()
        a, b = tk.Toplevel(root), tk.Toplevel(root)
        for w in (a, b):
            w.overrideredirect(True)
            w.geometry("100x80+100+100")
        root.update()
        ok = winapi.defer_move([(winapi.hwnd_of(a), 300, 200, None, None),
                                (winapi.hwnd_of(b), 420, 200, 150, 90)])
        root.update()
        try:
            self.assertTrue(ok)
            self.assertEqual((a.winfo_rootx(), a.winfo_rooty()), (300, 200))
            self.assertEqual((b.winfo_rootx(), b.winfo_width(), b.winfo_height()), (420, 150, 90))
        finally:
            root.destroy()

    def test_client_animations_flag_is_bool(self):
        self.assertIsInstance(winapi.client_animations_enabled(), bool)


if __name__ == "__main__":
    unittest.main()
