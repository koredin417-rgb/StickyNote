"""tools/make_release.py: the release zip a GitHub Release carries."""
import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import make_release  # noqa: E402


class MakeReleaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for rel, data in {"app/version.py": b'VERSION = "9.9.9"\n', "app/main.py": b"main",
                          "app/fonts/a.ttf": b"font", "app/__pycache__/main.cpython-315.pyc": b"pyc",
                          "runtime/python.exe": b"py", "runtime/Lib/__pycache__/os.pyc": b"pyc",
                          "runtime/Lib/os.py": b"os", "licenses/LICENSE.txt": b"lic",
                          "install.cmd": b"@echo off", "readme.txt": b"read", "preview.py": b"dev only"}.items():
            path = self.root / "StickyNote" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.out = self.root / "dist" / "StickyNote.zip"

    def tearDown(self):
        self._tmp.cleanup()

    def test_build(self):
        tag, sha = make_release.build(self.root, self.out)
        self.assertEqual(tag, "v9.9.9")
        self.assertEqual(sha, hashlib.sha256(self.out.read_bytes()).hexdigest())
        names = zipfile.ZipFile(self.out).namelist()
        self.assertTrue(all(n.startswith("StickyNote/") for n in names))
        self.assertEqual({n.split("/")[1] for n in names},
                         {"app", "runtime", "licenses", "install.cmd", "readme.txt"})
        self.assertFalse([n for n in names if "__pycache__" in n or n.endswith("preview.py")])
        self.assertIn("StickyNote/app/fonts/a.ttf", names)
        self.assertIn("StickyNote/runtime/Lib/os.py", names)
        self.assertFalse(self.out.with_name("StickyNote.zip.part").exists())

    def test_missing_part_is_refused(self):
        (self.root / "StickyNote" / "install.cmd").unlink()
        with self.assertRaises(SystemExit):
            make_release.build(self.root, self.out)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
