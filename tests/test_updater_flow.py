"""The Updater: check, download, verify, unpack, hand off to the new installer (all faked: no
network, no real installer)."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

from _support import Spy
import updater
import webget
from updater import Updater, clean_temp, read_result


def make_zip(path: Path, version="9.0.0", extra=None) -> Path:
    """A release zip as tools/make_release.py builds it (only what the updater looks at)."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("StickyNote/runtime/python.exe", b"py")
        z.writestr("StickyNote/app/install.py", b"# installer")
        z.writestr("StickyNote/app/version.py", f'VERSION = "{version}"\n')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


class FakeProc:
    """The installer as Popen gives it: wait() is how it ended (in real use it closes this app first)."""

    def __init__(self, code):
        self.code = code

    def wait(self, timeout=None):
        return self.code


def reply(tag="v9.0.0", size=0, sha=None) -> bytes:
    return json.dumps({"tag_name": tag, "body": "## New\n* faster", "draft": False, "prerelease": False,
                       "assets": [{"name": "StickyNote.zip", "browser_download_url": "https://example.test/z",
                                   "size": size, "digest": f"sha256:{sha}" if sha else None}]}).encode()


class UpdaterFlowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.temp = self.tmp / "temp"
        self.temp.mkdir()
        self.install_dir = self.tmp / "Programs" / "StickyNote"
        self.zip = make_zip(self.tmp / "built.zip")
        self.body = None            # what get answers (None: a release of self.zip)
        self.get = Spy(wraps=lambda url, headers: self.body if self.body is not None else self._reply())
        self.download = Spy(wraps=self._download)
        self.code = 0               # how the installer ends (0: it closed this app and installed)
        self.popen = Spy(wraps=lambda *a, **k: FakeProc(self.code))
        self.data = self.tmp / "data"

    def tearDown(self):
        self._tmp.cleanup()

    def _reply(self, **kw):
        data = self.zip.read_bytes()
        return reply(size=kw.get("size", len(data)), sha=kw.get("sha", hashlib.sha256(data).hexdigest()))

    def _download(self, url, path, headers, on_progress=None):
        data = self.zip.read_bytes()
        Path(path).write_bytes(data)
        if on_progress:
            on_progress(len(data) // 2, len(data))
            on_progress(len(data), len(data))
        return len(data)

    def updater(self, app_dir=None):
        return Updater(app_dir or self.install_dir / "app", get=self.get, download=self.download,
                       popen=self.popen, temp_dir=self.temp, install_dir=self.install_dir,
                       data_folder=self.data)

    def drain(self, u):
        end = time.perf_counter() + 2
        while u.pump() and time.perf_counter() < end:
            time.sleep(0.01)

    def installed(self, u):
        u.check()
        self.drain(u)
        self.assertEqual(u.state, "available")
        u.start_install()
        self.drain(u)
        return self.temp / "StickyNote-update-9.0.0" / "StickyNote"

    # ---- checking
    def test_check_finds_new(self):
        u = self.updater()
        u.check()
        self.drain(u)
        self.assertEqual((u.state, u.release.version), ("available", "9.0.0"))
        self.assertEqual(u.release.notes, "New\n• faster")
        self.assertEqual(self.get.calls[0][0][1], updater.HEADERS)

    def test_check_latest(self):
        self.body = reply(tag="v1.1.0", size=1)
        u = self.updater()
        u.check()
        self.drain(u)
        self.assertEqual(u.state, "latest")

    def test_check_network_error(self):
        self.get.raises = webget.WebError("down", status=None)
        u = self.updater()
        u.check()
        self.drain(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_network"))

    def test_check_rate_limited(self):
        for status in (403, 429):
            self.get.raises = webget.WebError("slow down", status=status)
            u = self.updater()
            u.check()
            self.drain(u)
            self.assertEqual((u.state, u.error), ("error", "upd_err_rate"))

    def test_check_bad_json(self):
        for body in (b"<html>", b'{"message": "odd"}', b'"text"'):
            self.body = body
            u = self.updater()
            u.check()
            self.drain(u)
            self.assertEqual((u.state, u.error), ("error", "upd_err_reply"))

    def test_second_check_while_busy_is_ignored(self):
        go = threading.Event()
        self.get.wraps = lambda url, headers: (go.wait(2), self._reply())[1]
        u = self.updater()
        u.check()
        u.check()
        self.assertEqual(u.state, "checking")
        go.set()
        self.drain(u)
        self.assertEqual((u.state, self.get.call_count), ("available", 1))

    def test_listeners_called_on_change(self):
        u = self.updater()
        seen = []
        u.listeners.append(lambda: seen.append(u.state))
        u.check()
        self.assertEqual(seen, ["checking"])
        self.drain(u)
        self.assertEqual(seen, ["checking", "available"])
        u.pump()                                        # nothing new: nobody called
        self.assertEqual(len(seen), 2)
        u.dismiss()
        self.assertEqual((u.state, seen[-1]), ("idle", "idle"))

    def test_check_again_after_dismiss(self):
        u = self.updater()
        u.check()
        self.drain(u)
        u.dismiss()
        u.check()
        self.drain(u)
        self.assertEqual((u.state, self.get.call_count), ("available", 2))

    # ---- installing
    def test_download_progress_shown(self):
        half, go = threading.Event(), threading.Event()

        def slow(url, path, headers, on_progress=None):
            on_progress(50, 100)
            half.set()
            go.wait(2)
            return self._download(url, path, headers, on_progress)
        self.download.wraps = slow
        u = self.updater()
        u.check()
        self.drain(u)
        u.start_install()
        self.assertEqual((u.state, u.progress), ("downloading", 0.0))
        half.wait(2)
        u.pump()
        self.assertEqual((u.state, u.progress), ("downloading", 0.5))
        go.set()
        self.drain(u)
        self.assertEqual((u.state, u.progress), ("installing", 1.0))

    def test_install_runs_new_installer(self):
        u = self.updater()
        x = self.installed(u)
        self.assertEqual(self.popen.call_count, 1)
        args, kwargs = self.popen.calls[0]
        self.assertEqual(args[0][0], str(x / "runtime" / "python.exe"))
        self.assertEqual(args[0][1:], [str(x / "app/install.py"), "--yes", "--dest", str(self.install_dir)])
        self.assertEqual(kwargs["cwd"], str(x / "app"))
        flags = kwargs["creationflags"]
        self.assertTrue(flags & subprocess.CREATE_NO_WINDOW and flags & subprocess.DETACHED_PROCESS)
        self.assertEqual(u.state, "installing")
        self.assertEqual(self.download.calls[0][0][2], updater.HEADERS)

    def test_size_mismatch(self):
        self.body = self._reply(size=5)
        u = self.updater()
        x = self.installed(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_verify"))
        self.assertFalse((x.parent / "StickyNote.zip").exists())
        self.assertEqual(self.popen.call_count, 0)

    def test_sha_mismatch(self):
        self.body = self._reply(sha="00" * 32)
        u = self.updater()
        x = self.installed(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_verify"))
        self.assertFalse((x.parent / "StickyNote.zip").exists())
        self.assertEqual(self.popen.call_count, 0)

    def test_no_digest_still_installs(self):
        self.body = self._reply(sha=None)
        u = self.updater()
        self.installed(u)
        self.assertEqual(u.state, "installing")

    def test_unsafe_zip_name(self):
        self.zip = make_zip(self.tmp / "evil.zip", extra={"StickyNote/../../evil.txt": b"x"})
        u = self.updater()
        self.installed(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_zip"))
        self.assertEqual(list(self.tmp.rglob("evil.txt")), [])
        self.assertEqual(self.popen.call_count, 0)

    def test_missing_installer_in_zip(self):
        with zipfile.ZipFile(self.tmp / "half.zip", "w") as z:
            z.writestr("StickyNote/app/version.py", 'VERSION = "9.0.0"\n')
        self.zip = self.tmp / "half.zip"
        u = self.updater()
        self.installed(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_zip"))

    def test_not_a_zip(self):
        (self.tmp / "junk.zip").write_bytes(b"not a zip at all")
        self.zip = self.tmp / "junk.zip"
        u = self.updater()
        self.installed(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_zip"))

    def test_zip_version_must_match_tag(self):
        self.zip = make_zip(self.tmp / "other.zip", version="1.3.0")
        u = self.updater()
        self.installed(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_zip"))
        self.assertEqual(self.popen.call_count, 0)

    def test_download_dir_starts_empty(self):
        stale = self.temp / "StickyNote-update-9.0.0" / "StickyNote" / "app" / "stale.py"
        stale.parent.mkdir(parents=True)
        stale.write_text("old")
        u = self.updater()
        self.installed(u)
        self.assertEqual(u.state, "installing")
        self.assertFalse(stale.exists())

    def test_disk_full(self):
        self.download.raises = webget.WebError("full", disk=True)
        u = self.updater()
        self.installed(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_disk"))

    def test_download_cut_off(self):
        self.download.raises = webget.WebError("cut", status=None)
        u = self.updater()
        self.installed(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_download"))

    def test_installer_fails_to_start(self):
        self.popen.raises = OSError("no")
        u = self.updater()
        self.installed(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_start"))

    def test_installer_ends_without_closing_app(self):     # it died: a broken zip's installer, an antivirus
        self.code = 1
        u = self.updater()
        self.installed(u)
        self.assertEqual((u.state, u.error), ("error", "upd_err_start"))

    def test_installer_reports_still_running(self):        # it couldn't close this app: said so, ended
        self.code = 1
        self.data.mkdir()
        (self.data / "update-result.json").write_text(
            '{"version": "9.0.0", "ok": false, "error": "still running"}', "utf-8")
        u = self.updater()
        self.installed(u)
        self.assertEqual((u.state, u.error, u.error_detail), ("error", "upd_err_install", "still running"))
        self.assertFalse((self.data / "update-result.json").exists())
        u.check()                                           # and a new check is possible again
        self.drain(u)
        self.assertEqual(u.state, "available")

    def test_elsewhere_never_installs(self):
        u = self.updater(app_dir=self.tmp / "repo" / "StickyNote" / "app")
        self.assertFalse(u.can_install)
        self.assertTrue(self.updater().can_install)
        u.check()
        self.drain(u)
        self.assertEqual(u.state, "available")
        u.start_install()
        self.drain(u)
        self.assertEqual(u.state, "available")
        self.assertEqual((self.download.call_count, self.popen.call_count), (0, 0))

    # ---- after the restart
    def test_read_result_once(self):
        data = self.tmp / "data"
        data.mkdir()
        (data / "update-result.json").write_text('{"version": "9.0.0", "ok": true, "error": ""}', "utf-8")
        self.assertEqual(read_result(data), {"version": "9.0.0", "ok": True, "error": ""})
        self.assertIsNone(read_result(data))
        (data / "update-result.json").write_text("{broken", "utf-8")
        self.assertIsNone(read_result(data))
        self.assertFalse((data / "update-result.json").exists())

    def test_clean_temp(self):
        for name in ("StickyNote-update-1.0.0", "StickyNote-update-9.9.9"):
            (self.temp / name / "StickyNote").mkdir(parents=True)
            (self.temp / name / "StickyNote" / "x").write_text("x")
        (self.temp / "other").mkdir()
        clean_temp(self.temp)
        self.assertEqual(sorted(p.name for p in self.temp.iterdir()), ["other"])


if __name__ == "__main__":
    unittest.main()
