import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from helpers import BASIC_ID, RICH_ID, TempDir, fixture_text

from shared_chat_exporter import fetch as F
from shared_chat_exporter import snapshot as S
from shared_chat_exporter.cache import SnapshotCache


class Handler(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", headers=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        Handler.hits.append(self.path)
        sid = self.path.split("/api/chat_snapshots/")[-1].split("?")[0]
        if sid == BASIC_ID:
            self._send(200, fixture_text("basic.json"))
        elif sid == "blocked":
            self._send(403, "<!DOCTYPE html><html><title>Just a moment...</title></html>", "text/html",
                       {"cf-mitigated": "challenge"})
        elif sid == "html200":
            self._send(200, "<html><body>challenge</body></html>", "text/html")
        elif sid == "denied":
            self._send(403, json.dumps({"type": "error", "error": {"type": "permission_error", "message": "no"}}))
        else:
            self._send(404, json.dumps({"type": "error", "error": {"type": "not_found_error", "message": "Not found"}}))


class DirectFetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.patch = mock.patch.object(S, "API_BASE", cls.base)
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def test_ok(self):
        text = F.fetch_direct(BASIC_ID)
        self.assertEqual(S.parse_snapshot_text(text)["uuid"], BASIC_ID)
        self.assertIn("rendering_mode=messages&render_all_tools=true", Handler.hits[-1])

    def test_blocked(self):
        for sid in ("blocked", "html200"):
            with self.subTest(sid=sid), self.assertRaises(F.Blocked):
                F.fetch_direct(sid)

    def test_not_found_and_denied(self):
        with self.assertRaises(F.NotFound):
            F.fetch_direct("nope")
        with self.assertRaises(F.AccessDenied):
            F.fetch_direct("denied")

    def test_fetcher_caches(self):
        with TempDir() as d:
            cache = SnapshotCache(d)
            f = F.Fetcher(via="direct", cache=cache, delay=0)
            n = len(Handler.hits)
            text, origin = f.get(BASIC_ID)
            self.assertEqual(origin, "direct")
            text2, origin2 = f.get(BASIC_ID)
            self.assertEqual((text2, origin2), (text, "cache"))
            self.assertEqual(len(Handler.hits), n + 1)
            self.assertEqual(cache.entries()[0]["title"], "파이썬 리스트 정렬 질문")
            _, origin3 = F.Fetcher(via="direct", cache=cache, refresh=True, delay=0).get(BASIC_ID)
            self.assertEqual(origin3, "direct")

    def test_auto_falls_back_to_manual_when_blocked(self):
        with TempDir() as d, mock.patch.object(F, "playwright_installed", return_value=False):
            def drop_file():
                time.sleep(0.4)
                (d / "blocked.json").write_text(fixture_text("rich.json").replace(RICH_ID, "blocked"), encoding="utf-8")

            threading.Thread(target=drop_file, daemon=True).start()
            f = F.Fetcher(via="auto", cache=None, open_browser=False, use_clipboard=False, watch_dirs=[d],
                          timeout=5, delay=0)
            text, origin = f.get("blocked")
            self.assertTrue(origin.startswith("file:"))
            self.assertEqual(S.parse_snapshot_text(text)["uuid"], "blocked")
            self.assertTrue(f._direct_blocked)

    def test_not_found_stops_auto(self):
        f = F.Fetcher(via="auto", cache=None, open_browser=False, use_clipboard=False, watch_dirs=[], delay=0)
        with self.assertRaises(F.NotFound):
            f.get("missing-id")


class ManualCaptureTest(unittest.TestCase):
    def test_clipboard_ignores_stale_and_other_conversations(self):
        other = fixture_text("basic.json")
        wanted = fixture_text("rich.json")
        seq = iter(["예전에 복사한 글", None, other, None, "Pretty-print\n" + wanted])
        text, origin = F.capture_manual(RICH_ID, open_browser=False, watch_dirs=[], timeout=5, poll_interval=0.01,
                                        clipboard_poll=lambda: next(seq, None))
        self.assertEqual(origin, "clipboard")
        self.assertEqual(S.parse_snapshot_text(text)["uuid"], RICH_ID)

    def test_stale_clipboard_with_right_snapshot_is_used(self):
        wanted = fixture_text("rich.json")
        text, origin = F.capture_manual(RICH_ID, open_browser=False, watch_dirs=[], timeout=2, poll_interval=0.01,
                                        clipboard_poll=lambda: wanted)
        self.assertEqual(origin, "clipboard")

    def test_watch_dir_skips_partial_and_old_files(self):
        with TempDir() as d:
            old = d / "old.json"
            old.write_text(fixture_text("rich.json"), encoding="utf-8")
            past = time.time() - 3600
            import os
            os.utime(old, (past, past))
            (d / "x.json.crdownload").write_text(fixture_text("rich.json"), encoding="utf-8")

            def drop():
                time.sleep(0.3)
                (d / f"{RICH_ID}.json").write_text(fixture_text("rich.json"), encoding="utf-8")

            threading.Thread(target=drop, daemon=True).start()
            text, origin = F.capture_manual(RICH_ID, open_browser=False, use_clipboard=False, watch_dirs=[d],
                                            timeout=5, poll_interval=0.05)
            self.assertTrue(origin.endswith(f"{RICH_ID}.json"))

    def test_timeout(self):
        with TempDir() as d:
            t0 = time.monotonic()
            with self.assertRaises(F.FetchError):
                F.capture_manual(RICH_ID, open_browser=False, use_clipboard=False, watch_dirs=[d], timeout=0.3,
                                 poll_interval=0.05)
            self.assertLess(time.monotonic() - t0, 3)

    def test_nothing_to_watch(self):
        with self.assertRaises(F.FetchError):
            F.capture_manual(RICH_ID, open_browser=False, use_clipboard=False, watch_dirs=[], timeout=1)


class BrowserTest(unittest.TestCase):
    def test_missing_playwright_is_reported(self):
        with mock.patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            with self.assertRaises(F.BrowserUnavailable):
                F.BrowserSession().fetch(RICH_ID, timeout=1)


if __name__ == "__main__":
    unittest.main()
