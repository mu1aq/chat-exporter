"""공유 링크에서 스냅샷 JSON을 받아옵니다.

claude.ai 앞단의 봇 차단(Cloudflare) 때문에 스크립트의 직접 요청은 대개 막힙니다.
그래서 순서대로 시도합니다.

1. cache   — 전에 받아둔 원본
2. direct  — 그냥 HTTP 요청 (막히지 않는 환경이면 바로 끝)
3. browser — Playwright가 설치돼 있으면 눈에 보이는 브라우저 창을 띄워서 받음
4. manual  — 기본 브라우저로 스냅샷 주소를 열고, 사용자가 복사(클립보드)하거나
             저장(다운로드 폴더)하면 자동으로 감지

브라우저 방식은 모두 사용자가 보는 진짜 브라우저를 씁니다. 확인 화면이 뜨면
사용자가 직접 통과해야 하고, 이 도구는 그걸 우회하지 않습니다.
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
    """스냅샷을 받지 못함."""


class Blocked(FetchError):
    """봇 차단 등으로 직접 요청이 막힘 → 다른 방법으로 넘어가면 됨."""


class NotFound(FetchError):
    pass


class AccessDenied(FetchError):
    pass


class BrowserUnavailable(FetchError):
    pass


def _looks_html(text: str) -> bool:
    head = text.lstrip()[:400].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<html" in head


NOT_FOUND_MSG = "공유 링크를 찾을 수 없습니다. 공유가 해제됐거나 주소가 틀렸을 수 있습니다."
DENIED_MSG = ("이 공유를 볼 권한이 없습니다. 팀·엔터프라이즈 플랜의 공유는 같은 조직 계정으로 "
              "로그인한 브라우저에서만 열립니다.")


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
            raise Blocked(f"직접 요청이 차단됐습니다 (HTTP {e.code}).") from None
        if e.code == 404:
            raise NotFound(NOT_FOUND_MSG) from None
        if e.code in (401, 403):
            raise AccessDenied(DENIED_MSG) from None
        raise FetchError(f"Claude 서버가 HTTP {e.code}를 돌려줬습니다.") from None
    except URLError as e:
        raise FetchError(f"네트워크 오류: {e.reason}") from None
    except (TimeoutError, OSError) as e:
        raise FetchError(f"네트워크 오류: {e}") from None
    try:
        parse_snapshot_text(text)
    except SnapshotError as e:
        if _looks_html(text):
            raise Blocked("직접 요청에 확인 페이지(HTML)가 돌아왔습니다.") from None
        raise FetchError(str(e)) from None
    return text


# ---------------------------------------------------------------- manual
def default_watch_dirs() -> List[Path]:
    """다운로드 폴더. 리눅스는 XDG 설정(예: ~/다운로드)을 따릅니다."""
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
    """사용자가 브라우저에서 복사하거나 저장한 스냅샷을 기다립니다. (텍스트, 출처) 반환."""
    ui = ui or NullUI()
    url = snapshot_api_url(share_id)
    dirs = list(watch_dirs) if watch_dirs is not None else default_watch_dirs()
    if clipboard_poll is None and use_clipboard and clip.available():
        clipboard_poll = clip.Watcher().poll
    if clipboard_poll is None and not dirs:
        raise FetchError(
            "클립보드도 다운로드 폴더도 감시할 수 없습니다. 스냅샷을 직접 저장한 뒤 파일 경로를 넘기거나 "
            "--watch-dir 로 저장 폴더를 지정하세요.\n  스냅샷 주소: " + url
        )

    opened = False
    if open_browser:
        try:
            opened = webbrowser.open(url, new=2)
        except Exception:
            opened = False
    s = ui.style
    ui.info(s("브라우저에서 스냅샷 JSON을 " + ("열었습니다." if opened else "열어 주세요:"), "bold"))
    ui.info("  " + s(url, "cyan"))
    ui.info("열린 탭에서 아래 중 하나만 하면 자동으로 이어집니다.")
    if clipboard_poll is not None:
        ui.info("  • 전체 선택 후 복사  (Ctrl+A → Ctrl+C, Mac은 ⌘A → ⌘C)")
    elif use_clipboard:
        ui.hint("  (" + clip.missing_hint() + ")")
    if dirs:
        ui.info("  • 페이지 저장  (Ctrl+S / ⌘S) → " + ", ".join(str(d) for d in dirs))
    ui.hint("  Firefox는 JSON 화면의 ‘원시 데이터(Raw Data)’ 탭에서 ‘복사’ 또는 ‘저장’을 누르세요.")
    ui.hint("  확인 화면이 뜨면 브라우저에서 먼저 통과하세요. 팀·엔터프라이즈 공유는 로그인한 브라우저여야 합니다.")

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
                ui.warn(f"{origin} 내용을 읽지 못했습니다: {e}")
            return None
        if snapshot_matches(snap, share_id):
            return text
        uid = str(snap.get("uuid"))
        if uid not in ignored:
            ignored.add(uid)
            ui.warn(f"{origin}에 다른 대화의 스냅샷이 있어 건너뜁니다: {snap.get('snapshot_name') or uid}")
        return None

    while True:
        if clipboard_poll is not None:
            text = clipboard_poll()
            got = consider(text, "클립보드", fresh=not first)
            if got:
                ui.end_status()
                return got, "clipboard"
        first = False
        for p in _new_files(dirs, started - 2, seen):
            try:
                text = decode_bytes(p.read_bytes())
            except OSError:
                continue
            got = consider(text, f"파일 {p.name}", fresh=True)
            if got:
                ui.end_status()
                return got, f"file:{p}"
        left = deadline - time.monotonic()
        if left <= 0:
            ui.end_status()
            raise FetchError(f"{int(timeout)}초 동안 스냅샷을 받지 못했습니다. --timeout 으로 늘리거나, "
                             "저장한 JSON 파일 경로를 직접 넘기세요.")
        ui.status(f"기다리는 중… {int(time.time() - started)}초 / {int(timeout)}초  (Ctrl+C 취소)")
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
    """Playwright로 띄운 (기본: 보이는) 브라우저 창 하나를 여러 링크에 재사용합니다.

    프로필을 캐시 폴더에 보관해서 확인 화면 통과·로그인 상태가 다음 실행에도 남습니다.
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
                "Playwright가 없습니다. 설치: pip install playwright && playwright install chromium"
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
        if hasattr(os, "geteuid") and os.geteuid() == 0:  # Docker 등 root로 실행할 때 Chrome이 요구
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
                "브라우저를 띄우지 못했습니다. `playwright install chromium` 을 실행했는지 확인하세요." + detail
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
                raise FetchError("브라우저 창이 닫혀서 중단했습니다.")
            res = None
            try:
                # 처음엔 공유 페이지로 이동하고, 이후엔 claude.ai를 벗어났을 때만 다시 이동
                if last_goto is None or (not page.url.startswith(API_BASE) and time.monotonic() - last_goto > 20):
                    last_goto = time.monotonic()
                    page.goto(target, wait_until="domcontentloaded", timeout=45000)
                res = page.evaluate(_JS_FETCH, snapshot_api_path(share_id))
            except PWError as e:
                if "closed" in str(e).lower():
                    raise FetchError("브라우저 창이 닫혀서 중단했습니다.") from None
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
                    self.ui.info("브라우저 창에서 이 공유를 볼 수 있는 계정으로 로그인해 주세요.")
                    told = True
            if not told:
                self.ui.info("브라우저 창에 확인 화면이 보이면 직접 완료해 주세요. 자동으로 이어집니다.")
                told = True
            if time.monotonic() > deadline:
                self.ui.end_status()
                raise FetchError(f"{int(timeout)}초 안에 브라우저에서 스냅샷을 받지 못했습니다.")
            self.ui.status(f"브라우저에서 받는 중… {int(time.time() - started)}초  (Ctrl+C 취소)")
            try:
                page.wait_for_timeout(1500)
            except PWError:
                raise FetchError("브라우저 창이 닫혀서 중단했습니다.") from None

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
    """캐시 → 직접 → 브라우저 → 수동 순서로 스냅샷을 구합니다."""

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
        """(스냅샷 텍스트, 받은 경로) 반환. 경로: cache/direct/browser/clipboard/file:…"""
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
                self.ui.hint(f"브라우저 자동 실행을 건너뜁니다: {str(e).splitlines()[0]}")
                errors.append(str(e))
                continue
            except Blocked as e:
                self._direct_blocked = True
                if self.via == "direct":
                    raise
                self.ui.hint(f"{e} 브라우저로 진행합니다.")
                errors.append(str(e))
                continue
            except AccessDenied as e:
                if self.via == "direct":
                    raise
                self.ui.hint(f"{e} 브라우저로 진행합니다.")
                errors.append(str(e))
                continue
            if self.cache is not None:
                try:
                    self.cache.put(share_id, text)
                except OSError as e:
                    self.ui.warn(f"캐시에 저장하지 못했습니다: {e}")
            return text, origin
        raise FetchError(errors[-1] if errors else "스냅샷을 받지 못했습니다.")

    def _run(self, method: str, share_id: str) -> Tuple[str, str]:
        if method == "direct":
            wait = self.delay - (time.monotonic() - self._last_direct)
            if wait > 0:
                time.sleep(wait)
            self._last_direct = time.monotonic()
            self.ui.status("Claude에서 직접 받는 중…")
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
        return "저장한 파일 " + Path(origin[5:]).name
    return {"cache": "캐시", "direct": "직접 요청", "browser": "브라우저 창", "clipboard": "클립보드",
            "stdin": "표준 입력"}.get(origin, origin)


__all__ = [
    "FetchError", "Blocked", "NotFound", "AccessDenied", "BrowserUnavailable", "fetch_direct", "capture_manual",
    "BrowserSession", "Fetcher", "default_watch_dirs", "playwright_installed", "describe_origin", "METHODS",
]
