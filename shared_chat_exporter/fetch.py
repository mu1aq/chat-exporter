"""Fetch snapshot JSON from a share link.

Bot protection in front of claude.ai (Cloudflare) usually blocks a script's
direct request, so methods are tried in order:

1. cache   — bytes fetched earlier
2. direct  — a plain HTTP request (done immediately where it is not blocked)
3. browser — if Playwright is installed, open a visible browser window to fetch
4. manual  — open the snapshot URL in the default browser and auto-detect when
             the user copies it (clipboard) or saves it (downloads folder)

Every browser method uses a real browser the user can see. If a challenge page
appears the user must pass it themselves; this tool does not bypass it.
"""

from __future__ import annotations

import importlib.util
import os
import re
import time
import webbrowser
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__
from . import clipboard as clip
from .cache import SnapshotCache, default_cache_dir
from .snapshot import (
    API_BASE,
    SnapshotError,
    decode_bytes,
    parse_snapshot_text,
    share_page_url,
    snapshot_api_path,
    snapshot_api_url,
    snapshot_matches,
)
from .term import UI, NullUI

USER_AGENT = f"claude-share-extract/{__version__} (+https://github.com/; terminal tool)"
METHODS = ("auto", "direct", "browser", "manual")


class FetchError(Exception):
    """The snapshot could not be fetched."""


class Blocked(FetchError):
    """The direct request was blocked (e.g. bot protection); fall back to another method."""


class NotFound(FetchError):
    pass


class AccessDenied(FetchError):
    pass


class BrowserUnavailable(FetchError):
    pass


def _looks_html(text: str) -> bool:
    head = text.lstrip()[:400].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<html" in head


NOT_FOUND_MSG = "Share link not found. The share may have been revoked or the URL is wrong."
DENIED_MSG = ("You do not have permission to view this share. Team/Enterprise shares open only in a "
              "browser signed in with the same organization account.")


# ---------------------------------------------------------------- direct
def fetch_direct(share_id: str, timeout: float = 20.0) -> str:
    req = Request(snapshot_api_url(share_id), headers={
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
    try:
        with urlopen(req, timeout=timeout) as r:
            text = decode_bytes(r.read())
    except HTTPError as e:
        body = ""
        try:
            body = decode_bytes(e.read()[:4096])
        except Exception:
            pass
        if (e.headers.get("cf-mitigated") == "challenge" or _looks_html(body)
                or e.code in (429, 503) or (e.code == 403 and not body.strip().startswith("{"))):
            raise Blocked(f"The direct request was blocked (HTTP {e.code}).") from None
        if e.code == 404:
            raise NotFound(NOT_FOUND_MSG) from None
        if e.code in (401, 403):
            raise AccessDenied(DENIED_MSG) from None
        raise FetchError(f"The Claude server returned HTTP {e.code}.") from None
    except URLError as e:
        raise FetchError(f"Network error: {e.reason}") from None
    except (TimeoutError, OSError) as e:
        raise FetchError(f"Network error: {e}") from None
    try:
        parse_snapshot_text(text)
    except SnapshotError as e:
        if _looks_html(text):
            raise Blocked("The direct request returned a challenge page (HTML).") from None
        raise FetchError(str(e)) from None
    return text


# ---------------------------------------------------------------- manual
def default_watch_dirs() -> List[Path]:
    """Downloads folder. On Linux it follows the XDG setting (e.g. ~/Downloads)."""
    dirs: List[Path] = []
    home = Path.home()
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
    try:
        m = re.search(r'^XDG_DOWNLOAD_DIR="?([^"\n]+)"?', cfg.read_text(encoding="utf-8"), re.M)
        if m:
            dirs.append(Path(m.group(1).replace("$HOME", str(home))).expanduser())
    except OSError:
        pass
    dirs.append(home / "Downloads")
    out: List[Path] = []
    for d in dirs:
        if d.is_dir() and d not in out:
            out.append(d)
    return out


_SKIP_SUFFIX = (".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload")
_MAX_BYTES = 64 * 1024 * 1024


def _new_files(dirs: List[Path], since: float, seen: set) -> List[Path]:
    found = []
    for d in dirs:
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if not e.is_file():
                    continue
                name = e.name.lower()
                if name.endswith(_SKIP_SUFFIX):
                    continue
                if not (name.endswith((".json", ".txt")) or "." not in name):
                    continue
                st = e.stat()
            except OSError:
                continue
            if st.st_mtime < since or not (20 <= st.st_size <= _MAX_BYTES):
                continue
            key = (e.path, st.st_mtime_ns, st.st_size)
            if key in seen:
                continue
            seen.add(key)
            found.append(Path(e.path))
    return found


def capture_manual(
    share_id: str,
    *,
    open_browser: bool = True,
    use_clipboard: bool = True,
    watch_dirs: Optional[List[Path]] = None,
    timeout: float = 300.0,
    poll_interval: float = 0.8,
    ui: Optional[UI] = None,
    clipboard_poll: Optional[Callable[[], Optional[str]]] = None,
) -> Tuple[str, str]:
    """Wait for a snapshot the user copies or saves in the browser. Returns (text, origin)."""
    ui = ui or NullUI()
    url = snapshot_api_url(share_id)
    dirs = list(watch_dirs) if watch_dirs is not None else default_watch_dirs()
    if clipboard_poll is None and use_clipboard and clip.available():
        clipboard_poll = clip.Watcher().poll
    if clipboard_poll is None and not dirs:
        raise FetchError(
            "Cannot watch the clipboard or a downloads folder. Save the snapshot yourself and pass the "
            "file path, or set a folder to watch with --watch-dir.\n  snapshot URL: " + url
        )

    opened = False
    if open_browser:
        try:
            opened = webbrowser.open(url, new=2)
        except Exception:
            opened = False
    s = ui.style
    ui.info(s(("Opened" if opened else "Please open") + " the snapshot JSON in your browser:", "bold"))
    ui.info("  " + s(url, "cyan"))
    ui.info("Do just one of the following in the open tab and it continues automatically.")
    if clipboard_poll is not None:
        ui.info("  • Select all and copy  (Ctrl+A → Ctrl+C, ⌘A → ⌘C on Mac)")
    elif use_clipboard:
        ui.hint("  (" + clip.missing_hint() + ")")
    if dirs:
        ui.info("  • Save the page  (Ctrl+S / ⌘S) → " + ", ".join(str(d) for d in dirs))
    ui.hint("  In Firefox, use 'Copy' or 'Save' on the 'Raw Data' tab of the JSON view.")
    ui.hint("  If a challenge page appears, pass it in the browser first. Team/Enterprise shares need a signed-in browser.")

    started = time.time()
    seen: set = set()
    ignored: set = set()
    first = True
    deadline = time.monotonic() + timeout

    def consider(text: Optional[str], origin: str, fresh: bool) -> Optional[str]:
        if not text or "chat_messages" not in text:
            return None
        try:
            snap = parse_snapshot_text(text)
        except SnapshotError as e:
            if fresh:
                ui.warn(f"Could not read {origin}: {e}")
            return None
        if snapshot_matches(snap, share_id):
            return text
        uid = str(snap.get("uuid"))
        if uid not in ignored:
            ignored.add(uid)
            ui.warn(f"{origin} holds a snapshot of a different conversation, skipping: {snap.get('snapshot_name') or uid}")
        return None

    while True:
        if clipboard_poll is not None:
            text = clipboard_poll()
            got = consider(text, "clipboard", fresh=not first)
            if got:
                ui.end_status()
                return got, "clipboard"
        first = False
        for p in _new_files(dirs, started - 2, seen):
            try:
                text = decode_bytes(p.read_bytes())
            except OSError:
                continue
            got = consider(text, f"file {p.name}", fresh=True)
            if got:
                ui.end_status()
                return got, f"file:{p}"
        left = deadline - time.monotonic()
        if left <= 0:
            ui.end_status()
            raise FetchError(f"No snapshot received within {int(timeout)}s. Increase it with --timeout, "
                             "or pass the path to a saved JSON file.")
        ui.status(f"Waiting… {int(time.time() - started)}s / {int(timeout)}s  (Ctrl+C to cancel)")
        time.sleep(min(poll_interval, max(0.05, left)))


# ---------------------------------------------------------------- browser
_JS_FETCH = """async (path) => {
  try {
    const r = await fetch(path, {credentials: 'include', headers: {accept: 'application/json'}});
    return {status: r.status, text: await r.text()};
  } catch (e) { return {status: 0, text: String(e)}; }
}"""


def playwright_installed() -> bool:
    try:
        return importlib.util.find_spec("playwright") is not None
    except (ImportError, ValueError):
        return False


class BrowserSession:
    """Reuse one Playwright browser window (visible by default) across several links.

    The profile is kept in the cache folder so challenge passes and login state
    persist to the next run.
    """

    def __init__(self, *, channel: Optional[str] = None, executable: Optional[str] = None,
                 headless: bool = False, profile_dir: Optional[Path] = None, ui: Optional[UI] = None) -> None:
        self.channel = channel
        self.executable = executable
        self.headless = headless
        self.profile_dir = Path(profile_dir) if profile_dir else default_cache_dir() / "browser-profile"
        self.ui = ui or NullUI()
        self._pw = None
        self._ctx = None
        self._page = None

    def _start(self) -> None:
        try:
            from playwright.sync_api import Error as PWError
            from playwright.sync_api import sync_playwright
        except Exception:
            raise BrowserUnavailable(
                "Playwright is not available. Install: pip install playwright && playwright install chromium"
            ) from None
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        attempts: List[Dict[str, object]] = []
        if self.executable:
            attempts.append({"executable_path": self.executable})
        elif self.channel:
            attempts.append({"channel": self.channel} if self.channel != "chromium" else {})
        else:
            attempts += [{"channel": "chrome"}, {"channel": "msedge"}, {}]
        extra: Dict[str, object] = {}
        if hasattr(os, "geteuid") and os.geteuid() == 0:  # Chrome requires this when run as root, e.g. in Docker
            extra["args"] = ["--no-sandbox"]
        last = None
        for kw in attempts:
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(
                    str(self.profile_dir), headless=self.headless, viewport={"width": 1100, "height": 800},
                    **extra, **kw)
                break
            except PWError as e:
                last = e
        if self._ctx is None:
            self.close()
            detail = ("\n  " + str(last).strip().splitlines()[0]) if last else ""
            raise BrowserUnavailable(
                "Could not launch a browser. Check that you ran `playwright install chromium`." + detail
            )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def fetch(self, share_id: str, timeout: float = 180.0) -> str:
        if self._ctx is None:
            self._start()
        from playwright.sync_api import Error as PWError
        page = self._page
        target = share_page_url(share_id)
        deadline = time.monotonic() + timeout
        last_goto = None
        told = False
        started = time.time()
        while True:
            if page.is_closed():
                raise FetchError("The browser window was closed; stopping.")
            res = None
            try:
                # Navigate to the share page first; afterwards only re-navigate when off claude.ai
                if last_goto is None or (not page.url.startswith(API_BASE) and time.monotonic() - last_goto > 20):
                    last_goto = time.monotonic()
                    page.goto(target, wait_until="domcontentloaded", timeout=45000)
                res = page.evaluate(_JS_FETCH, snapshot_api_path(share_id))
            except PWError as e:
                if "closed" in str(e).lower():
                    raise FetchError("The browser window was closed; stopping.") from None
            if res:
                status, text = res.get("status"), res.get("text") or ""
                if status == 200:
                    try:
                        parse_snapshot_text(text)
                        self.ui.end_status()
                        return text
                    except SnapshotError:
                        pass
                elif status == 404:
                    self.ui.end_status()
                    raise NotFound(NOT_FOUND_MSG)
                elif status in (401, 403) and not _looks_html(text) and not told:
                    self.ui.info("Sign in, in the browser window, with an account that can view this share.")
                    told = True
            if not told:
                self.ui.info("If a challenge page appears in the browser window, complete it yourself. It continues automatically.")
                told = True
            if time.monotonic() > deadline:
                self.ui.end_status()
                raise FetchError(f"No snapshot received from the browser within {int(timeout)}s.")
            self.ui.status(f"Fetching in the browser… {int(time.time() - started)}s  (Ctrl+C to cancel)")
            try:
                page.wait_for_timeout(1500)
            except PWError:
                raise FetchError("The browser window was closed; stopping.") from None

    def close(self) -> None:
        for obj, meth in ((self._ctx, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    getattr(obj, meth)()
                except Exception:
                    pass
        self._ctx = self._pw = self._page = None


# ---------------------------------------------------------------- orchestration
class Fetcher:
    """Obtain a snapshot in order: cache, direct, browser, manual."""

    def __init__(self, *, via: str = "auto", cache: Optional[SnapshotCache] = None, refresh: bool = False,
                 ui: Optional[UI] = None, timeout: float = 300.0, open_browser: bool = True,
                 use_clipboard: bool = True, watch_dirs: Optional[List[Path]] = None, delay: float = 1.0,
                 browser_channel: Optional[str] = None, browser_path: Optional[str] = None,
                 headless: bool = False) -> None:
        if via not in METHODS:
            raise ValueError(f"via must be one of {METHODS}")
        self.via = via
        self.cache = cache
        self.refresh = refresh
        self.ui = ui or NullUI()
        self.timeout = timeout
        self.open_browser = open_browser
        self.use_clipboard = use_clipboard
        self.watch_dirs = watch_dirs
        self.delay = delay
        self.browser_opts = {"channel": browser_channel, "executable": browser_path, "headless": headless}
        self._browser: Optional[BrowserSession] = None
        self._direct_blocked = False
        self._browser_failed = False
        self._last_direct = 0.0

    def _plan(self) -> List[str]:
        if self.via != "auto":
            return [self.via]
        plan = [] if self._direct_blocked else ["direct"]
        if playwright_installed() and not self._browser_failed:
            plan.append("browser")
        plan.append("manual")
        return plan

    def get(self, share_id: str) -> Tuple[str, str]:
        """Return (snapshot text, origin). Origin: cache/direct/browser/clipboard/file:…"""
        if self.cache is not None and not self.refresh:
            text = self.cache.get(share_id)
            if text:
                return text, "cache"
        errors: List[str] = []
        for method in self._plan():
            try:
                text, origin = self._run(method, share_id)
            except BrowserUnavailable as e:
                self._browser_failed = True
                if self.via == "browser":
                    raise
                self.ui.hint(f"Skipping automatic browser launch: {str(e).splitlines()[0]}")
                errors.append(str(e))
                continue
            except Blocked as e:
                self._direct_blocked = True
                if self.via == "direct":
                    raise
                self.ui.hint(f"{e} Continuing with the browser.")
                errors.append(str(e))
                continue
            except AccessDenied as e:
                if self.via == "direct":
                    raise
                self.ui.hint(f"{e} Continuing with the browser.")
                errors.append(str(e))
                continue
            if self.cache is not None:
                try:
                    self.cache.put(share_id, text)
                except OSError as e:
                    self.ui.warn(f"Could not save to cache: {e}")
            return text, origin
        raise FetchError(errors[-1] if errors else "Could not fetch the snapshot.")

    def _run(self, method: str, share_id: str) -> Tuple[str, str]:
        if method == "direct":
            wait = self.delay - (time.monotonic() - self._last_direct)
            if wait > 0:
                time.sleep(wait)
            self._last_direct = time.monotonic()
            self.ui.status("Fetching directly from Claude…")
            try:
                return fetch_direct(share_id), "direct"
            finally:
                self.ui.end_status()
        if method == "browser":
            if self._browser is None:
                self._browser = BrowserSession(ui=self.ui, profile_dir=(self.cache.root / "browser-profile")
                                               if self.cache is not None else None, **self.browser_opts)
            return self._browser.fetch(share_id, timeout=self.timeout), "browser"
        return capture_manual(share_id, open_browser=self.open_browser, use_clipboard=self.use_clipboard,
                              watch_dirs=self.watch_dirs, timeout=self.timeout, ui=self.ui)

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None


def describe_origin(origin: str) -> str:
    if origin.startswith("file:"):
        return "saved file " + Path(origin[5:]).name
    return {"cache": "cache", "direct": "direct request", "browser": "browser window", "clipboard": "clipboard",
            "stdin": "standard input"}.get(origin, origin)


__all__ = [
    "FetchError", "Blocked", "NotFound", "AccessDenied", "BrowserUnavailable", "fetch_direct", "capture_manual",
    "BrowserSession", "Fetcher", "default_watch_dirs", "playwright_installed", "describe_origin", "METHODS",
]
