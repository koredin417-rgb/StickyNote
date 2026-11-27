"""install.py --yes: the in-app update's quiet run (no questions, a result file, always an app after)."""
import builtins
import json
import tempfile
import unittest
from pathlib import Path

from _support import Spy, patched
import install


def version_of(src: Path) -> str:
    return install.read_version((src / "app" / "version.py").read_text(encoding="utf-8"))


class _Asked(AssertionError):
    pass


def _no_input(*_a, **_k):
    raise _Asked("input() was called")


class InstallQuietTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.src, self.dest = root / "src" / "StickyNote", root / "Programs" / "StickyNote"
        self.data, links = root / "data", root / "links"
        links.mkdir()
        for rel, data in {"runtime/python.exe": b"py", "app/main.py": b"main", "licenses/L.txt": b"l",
                          "app/version.py": b'VERSION = "9.9.9"\n'}.items():
            (self.src / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.src / rel).write_bytes(data)
        self.args = ["--source", str(self.src), "--dest", str(self.dest), "--link-dir", str(links)]
        self.launch = Spy()
        self.running = Spy(wraps=lambda name: False)
        self.pause = Spy()
        self._patches = [patched(install, "data_folder", lambda: self.data),
                         patched(install, "launch", self.launch),
                         patched(install.winapi, "instance_running", self.running),
                         patched(install.shortcut, "create", lambda *a, **k: None),
                         patched(install, "_icons_changed", lambda: None),
                         patched(install, "_app_processes", lambda *a, **k: []),
                         patched(install, "_pause", self.pause),
                         patched(builtins, "input", _no_input)]
        for p in self._patches:
            p.__enter__()

    def tearDown(self):
        for p in reversed(self._patches):
            p.__exit__(None, None, None)
        self._tmp.cleanup()

    def result(self):
        return json.loads((self.data / install.RESULT_FILE).read_text("utf-8"))

    def test_yes_writes_ok_result(self):
        self.assertEqual(install.main(["--yes", *self.args]), 0)
        self.assertEqual(self.result(), {"version": version_of(self.src), "ok": True, "error": ""})
        self.assertEqual(version_of(self.src), "9.9.9")
        self.assertEqual(self.launch.call_count, 1)
        self.assertEqual((self.dest / "app/main.py").read_bytes(), b"main")
        self.assertEqual(self.pause.call_count, 0)

    def test_yes_failure_writes_error_and_relaunches(self):
        with patched(install, "install", Spy(raises=OSError("disk"))):
            self.assertEqual(install.main(["--yes", *self.args]), 1)
        result = self.result()
        self.assertFalse(result["ok"])
        self.assertIn("disk", result["error"])
        self.assertEqual(self.launch.call_count, 1)

    def test_yes_still_running(self):
        self.running.wraps = lambda name: True
        with patched(install, "close_running", lambda *a, **k: False):
            self.assertEqual(install.main(["--yes", *self.args]), 1)
        self.assertEqual(self.result()["error"], "still running")
        self.assertEqual(self.launch.call_count, 0)
        self.assertFalse((self.dest / "app").exists())

    def test_yes_closes_without_asking(self):     # running at first; closed once asked over waker
        answers = iter([True])
        self.running.wraps = lambda name: next(answers, False)
        self.assertEqual(install.main(["--yes", *self.args]), 0)
        self.assertTrue(self.result()["ok"])

    def test_without_yes_no_result_file(self):
        install.main(self.args)
        self.assertFalse((self.data / install.RESULT_FILE).exists())

    def test_helpers_run_without_window(self):     # (the update's installer has no console to share)
        class Done:
            stdout = ""
        run = Spy(wraps=lambda *a, **k: Done())
        with patched(install.subprocess, "run", run):
            _REAL_APP_PROCESSES(self.dest)
        self.assertEqual(run.calls[-1][1].get("creationflags"), install.NO_WINDOW)


    def test_process_list_reads_hangul_paths(self):  # e.g. C:\Users\김민호\AppData\Local\Programs\...
        self.assertEqual(install._powershell("Write-Output 'C:\\Users\\김민호'").strip(), "C:\\Users\\김민호")


_REAL_APP_PROCESSES = install._app_processes        # (setUp stands in for it)


if __name__ == "__main__":
    unittest.main()
