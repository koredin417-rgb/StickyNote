"""The installer swaps files with a backup: a failed or killed install puts the old version back."""
import os
import tempfile
import unittest
from pathlib import Path

from _support import Spy, patched
import install


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def tree(root: Path, files: dict) -> None:
    for rel, data in files.items():
        write(root / rel, data)


BASE = {"runtime/python.exe": b"py", "app/main.py": b"main", "licenses/LICENSE.txt": b"lic"}


class InstallSwapTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.src, self.dest = root / "src" / "StickyNote", root / "Programs" / "StickyNote"
        self._icons = patched(install, "_icons_changed", lambda: None)
        self._icons.__enter__()

    def tearDown(self):
        self._icons.__exit__(None, None, None)
        self._tmp.cleanup()

    def test_fresh_install_and_update(self):
        tree(self.src, {**BASE, "app/a.py": b"one", "app/old.py": b"x"})
        install.install(self.src, self.dest, [])
        self.assertEqual((self.dest / "app/a.py").read_bytes(), b"one")
        self.assertEqual((self.dest / "runtime/python.exe").read_bytes(), b"py")
        (self.src / "app/old.py").unlink()
        write(self.src / "app/a.py", b"two")
        install.install(self.src, self.dest, [])
        self.assertEqual((self.dest / "app/a.py").read_bytes(), b"two")
        self.assertFalse((self.dest / "app/old.py").exists())
        self.assertFalse((self.dest / install.BACKUP_DIR).exists())
        self.assertEqual(list(self.dest.rglob("*.new")), [])

    def test_failure_restores_old_files(self):
        tree(self.dest, {**BASE, "app/a.py": b"old", "app/gone.py": b"gone"})
        tree(self.src, {**BASE, "app/a.py": b"new", "app/b.py": b"add"})
        real, calls = os.replace, []

        def flaky(a, b):
            calls.append((a, b))
            if len(calls) == 2:
                raise OSError("disk")
            return real(a, b)
        with patched(install.os, "replace", flaky):
            with self.assertRaises(OSError):
                install.install(self.src, self.dest, [])
        self.assertEqual((self.dest / "app/a.py").read_bytes(), b"old")
        self.assertTrue((self.dest / "app/gone.py").exists())
        self.assertFalse((self.dest / "app/b.py").exists())
        self.assertFalse((self.dest / install.BACKUP_DIR).exists())
        self.assertEqual(sorted(p.name for p in (self.dest / "app").glob("*.new")), [])

    def test_interrupted_install_is_recovered(self):
        # as a killed install leaves it: a.py replaced (new in place, old in the backup), b.py added
        backup = self.dest / install.BACKUP_DIR
        tree(self.dest, {**BASE, "app/a.py": b"new", "app/b.py": b"add"})
        write(backup / "app/a.py", b"old")
        (backup / install.JOURNAL).write_text("replaced\tapp/a.py\nadded\tapp/b.py\n", encoding="utf-8")
        self.assertTrue(install.recover(self.dest))
        self.assertEqual((self.dest / "app/a.py").read_bytes(), b"old")
        self.assertFalse((self.dest / "app/b.py").exists())
        self.assertFalse(backup.exists())
        self.assertFalse(install.recover(self.dest))

    def test_removed_file_in_removed_folder_comes_back(self):
        backup = self.dest / install.BACKUP_DIR
        tree(self.dest, BASE)
        write(backup / "app/sub/x.py", b"x")            # its folder was removed too
        (backup / install.JOURNAL).write_text("removed\tapp/sub/x.py\n", encoding="utf-8")
        self.assertTrue(install.recover(self.dest))
        self.assertEqual((self.dest / "app/sub/x.py").read_bytes(), b"x")

    def test_install_recovers_first(self):
        tree(self.src, {**BASE, "app/a.py": b"a"})
        with patched(install, "recover", Spy(wraps=install.recover)) as spy:
            install.install(self.src, self.dest, [])
        self.assertEqual(spy.calls[0][0], (self.dest,))

    def test_unchanged_files_not_touched(self):
        tree(self.src, {**BASE, "app/a.py": b"one"})
        install.install(self.src, self.dest, [])
        main = self.dest / "app/main.py"
        os.utime(main, (1_000_000_000, 1_000_000_000))
        write(self.src / "app/a.py", b"two")
        real, moved = os.replace, []
        with patched(install.os, "replace", lambda a, b: (moved.append(Path(b)), real(a, b))[1]):
            install.install(self.src, self.dest, [])
        self.assertEqual(main.stat().st_mtime, 1_000_000_000)
        self.assertNotIn("main.py", {p.name for p in moved})
        self.assertIn("a.py", {p.name for p in moved})


if __name__ == "__main__":
    unittest.main()
