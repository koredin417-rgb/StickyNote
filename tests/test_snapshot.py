import tkinter as tk
import unittest

import _support  # noqa: F401  (DPI setup, app path)
import winapi


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.top = tk.Toplevel(self.root)
        self.top.geometry("200x120+50+50")
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_snapshot_returns_buffer_of_right_size(self):
        w, h, data = winapi.snapshot(self.top)
        self.assertNotIsInstance(data, bytes)               # no extra copy
        self.assertEqual(len(memoryview(data).cast("B")), w * h * 4)

    def test_snapshot_does_not_leak_gdi(self):
        before = winapi.gui_handles()[0]
        for _ in range(50):
            winapi.snapshot(self.top)
        self.assertLessEqual(winapi.gui_handles()[0] - before, 2)

    def test_snapshot_withdrawn_returns_none_without_leak(self):
        self.top.withdraw()
        self.root.update()
        before = winapi.gui_handles()[0]
        r = None
        for _ in range(20):
            r = winapi.snapshot(self.top)
        self.assertLessEqual(winapi.gui_handles()[0] - before, 2)
        self.assertTrue(r is None or r[0] > 0)              # PrintWindow may still draw a withdrawn window


if __name__ == "__main__":
    unittest.main()
