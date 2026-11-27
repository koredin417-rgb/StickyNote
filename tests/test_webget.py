"""webget: HTTP(S) through WinHTTP, against a small server on 127.0.0.1 (plain http://).
The bundled runtime has no http package, so the server answers by hand on socketserver."""
import os
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path

import webget

BIG = bytes(range(256)) * 1171 + bytes(224)         # 300_000 bytes
assert len(BIG) == 300_000


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline().decode("latin-1")
        headers = {}
        while True:
            h = self.rfile.readline().decode("latin-1").strip()
            if not h:
                break
            name, _, value = h.partition(":")
            headers[name.strip().lower()] = value.strip()
        path = line.split(" ")[1] if line.count(" ") >= 2 else "/"
        if path == "/hello":
            self.reply(200, b"hi")
        elif path == "/echo-agent":
            self.reply(200, headers.get("user-agent", "").encode())
        elif path == "/moved":
            self.reply(302, b"", extra="Location: /hello\r\n")
        elif path == "/big":
            self.reply(200, BIG)
        elif path == "/short":                          # says 1000 bytes, sends 500, hangs up
            self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\nConnection: close\r\n\r\n" + bytes(500))
        else:
            self.reply(404, b"no")

    def reply(self, status, body, extra=""):
        head = (f"HTTP/1.1 {status} X\r\nContent-Length: {len(body)}\r\nConnection: close\r\n{extra}\r\n")
        self.wfile.write(head.encode("latin-1") + body)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class WebGetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = _Server(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def url(self, path):
        return f"http://127.0.0.1:{self.server.server_address[1]}{path}"

    def test_get_ok(self):
        self.assertEqual(webget.get(self.url("/hello"), {"User-Agent": "t"}), b"hi")

    def test_headers_sent(self):
        self.assertEqual(webget.get(self.url("/echo-agent"), {"User-Agent": "StickyNote-updater"}),
                         b"StickyNote-updater")

    def test_redirect_followed(self):
        self.assertEqual(webget.get(self.url("/moved"), {}), b"hi")

    def test_status_error(self):
        with self.assertRaises(webget.WebError) as cm:
            webget.get(self.url("/missing"), {})
        self.assertEqual(cm.exception.status, 404)

    def test_no_server(self):
        with self.assertRaises(webget.WebError) as cm:
            webget.get("http://127.0.0.1:9/", {}, timeout=2)
        self.assertIsNone(cm.exception.status)

    def test_download_progress(self):
        seen = []
        n = webget.download(self.url("/big"), self.tmp / "f.bin", {}, lambda d, t: seen.append((d, t)))
        self.assertEqual(n, 300_000)
        self.assertEqual((self.tmp / "f.bin").read_bytes(), BIG)
        self.assertEqual(seen[-1], (300_000, 300_000))
        self.assertFalse((self.tmp / "f.bin.part").exists())

    def test_download_cut_off(self):                    # fewer bytes than promised: an error, nothing left
        with self.assertRaises(webget.WebError):
            webget.download(self.url("/short"), self.tmp / "f.bin", {}, timeout=5)
        self.assertEqual(list(self.tmp.iterdir()), [])

    @unittest.skipUnless(os.environ.get("STICKYNOTE_NET_TESTS") == "1", "network")
    def test_github_https(self):
        body = webget.get("https://api.github.com/repos/koredin417-rgb/StickyNote",
                          {"User-Agent": "StickyNote-updater"})
        self.assertIn(b'"full_name"', body)


if __name__ == "__main__":
    unittest.main()
