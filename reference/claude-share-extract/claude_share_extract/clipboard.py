"""운영체제 클립보드 읽기/쓰기 (외부 패키지 없이).

- Windows: Win32 API (ctypes), 실패하면 PowerShell
- macOS: pbpaste / pbcopy
- Linux: wl-paste/wl-copy (Wayland), xclip, xsel
- WSL: powershell.exe / clip.exe
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

_ENV_UTF8 = dict(os.environ, LANG=os.environ.get("LANG") or "en_US.UTF-8", LC_ALL=os.environ.get("LC_ALL") or "en_US.UTF-8")


def _is_wsl() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        return "microsoft" in platform.uname().release.lower()
    except Exception:
        return False


def _run(cmd: List[str], data: Optional[str] = None, timeout: float = 5.0) -> Optional[str]:
    try:
        p = subprocess.run(cmd, input=data.encode("utf-8") if data is not None else None,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, env=_ENV_UTF8)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", errors="replace")


# ---------- Windows ----------
def _win_api():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return ctypes, user32, kernel32


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _win_open(user32) -> bool:
    import time

    for _ in range(10):  # 다른 프로그램이 잠깐 쥐고 있을 수 있음
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.05)
    return False


def _win_read() -> Optional[str]:
    try:
        ctypes, user32, kernel32 = _win_api()
    except Exception:
        return None
    if not _win_open(user32):
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def _win_write(text: str) -> bool:
    try:
        ctypes, user32, kernel32 = _win_api()
    except Exception:
        return False
    data = text.encode("utf-16-le") + b"\x00\x00"
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        return False
    p = kernel32.GlobalLock(h)
    if not p:
        kernel32.GlobalFree(h)
        return False
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    if not _win_open(user32):
        kernel32.GlobalFree(h)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            kernel32.GlobalFree(h)
            return False
        return True  # 성공하면 메모리는 시스템 소유
    finally:
        user32.CloseClipboard()


_PS_READ = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"


def _backends() -> Tuple[Optional[List[str]], Optional[List[str]], str]:
    """(읽기 명령, 쓰기 명령, 이름). Windows는 ctypes를 따로 씁니다."""
    if sys.platform == "darwin":
        return ["pbpaste"], ["pbcopy"], "pbpaste"
    if _is_wsl() and shutil.which("powershell.exe"):
        return (["powershell.exe", "-NoProfile", "-Command", _PS_READ],
                ["clip.exe"] if shutil.which("clip.exe") else None, "powershell.exe")
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        return ["wl-paste", "--no-newline"], ["wl-copy"] if shutil.which("wl-copy") else None, "wl-clipboard"
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard", "-o"], ["xclip", "-selection", "clipboard", "-i"], "xclip"
    if shutil.which("xsel"):
        return ["xsel", "--clipboard", "--output"], ["xsel", "--clipboard", "--input"], "xsel"
    return None, None, ""


def available() -> bool:
    if os.name == "nt":
        return True
    return _backends()[0] is not None


def missing_hint() -> str:
    if sys.platform.startswith("linux"):
        return "클립보드를 읽으려면 xclip, xsel, wl-clipboard 중 하나를 설치하세요 (예: sudo apt install xclip)."
    return "이 환경에서는 클립보드를 쓸 수 없습니다."


def read() -> Optional[str]:
    """클립보드 텍스트. 읽을 수 없으면 None."""
    if os.name == "nt":
        text = _win_read()
        if text is None:
            text = _run(["powershell", "-NoProfile", "-Command", _PS_READ])
        return text
    cmd = _backends()[0]
    return _run(cmd) if cmd else None


def write(text: str) -> bool:
    if os.name == "nt":
        return _win_write(text)
    cmd = _backends()[1]
    if not cmd:
        return False
    if cmd == ["clip.exe"]:  # WSL: clip.exe는 UTF-16LE + BOM을 받아야 한글이 깨지지 않음
        try:
            subprocess.run(cmd, input=b"\xff\xfe" + text.encode("utf-16-le"), timeout=5, check=True)
            return True
        except (OSError, subprocess.SubprocessError):
            return False
    return _run(cmd, data=text) is not None


class Watcher:
    """클립보드가 바뀌었는지 확인합니다 (Windows는 시퀀스 번호로 싸게 확인)."""

    def __init__(self) -> None:
        self._seq = None
        self._last: Optional[int] = None
        if os.name == "nt":
            try:
                _, user32, _ = _win_api()
                self._seq = user32.GetClipboardSequenceNumber
            except Exception:
                self._seq = None

    def poll(self) -> Optional[str]:
        """바뀐 내용이 있으면 돌려주고, 처음 호출이면 현재 내용을 돌려줍니다."""
        if self._seq is not None:
            n = int(self._seq())
            if n == self._last:
                return None
            self._last = n
            return read()
        text = read()
        if text is None:
            return None
        h = hash(text)
        if h == self._last:
            return None
        self._last = h
        return text
