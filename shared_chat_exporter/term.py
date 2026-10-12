"""Terminal output: color, progress bar, pager, East Asian width alignment."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unicodedata
from typing import IO, Optional


def _enable_windows_vt(stream: IO) -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.GetStdHandle(-11 if stream is sys.stdout else -12)
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def setup_streams() -> None:
    """Avoid crashing on encoding errors in the Windows console."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def isatty(stream: IO) -> bool:
    try:
        return stream.isatty()
    except Exception:
        return False


def use_color(stream: IO, force: Optional[bool] = None) -> bool:
    if force is not None:
        return force
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return isatty(stream) and _enable_windows_vt(stream)


def unicode_ok(stream: IO) -> bool:
    enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
    return enc.startswith("utf")


class Style:
    CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34",
             "magenta": "35", "cyan": "36", "gray": "90"}

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *names: str) -> str:
        if not self.enabled or not names:
            return text
        codes = ";".join(self.CODES[n] for n in names)
        return f"\x1b[{codes}m{text}\x1b[0m"


def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 0 if unicodedata.combining(ch) else 1
               for ch in text)


def pad(text: str, cols: int) -> str:
    return text + " " * max(0, cols - width(text))


def truncate(text: str, cols: int) -> str:
    if width(text) <= cols:
        return text
    out, w = [], 0
    for ch in text:
        cw = width(ch)
        if w + cw > cols - 1:
            break
        out.append(ch)
        w += cw
    return "".join(out) + "…"


class UI:
    """Send progress messages to stderr so stdout carries only exported data."""

    def __init__(self, quiet: bool = False, color: Optional[bool] = None, stream: Optional[IO] = None) -> None:
        self.stream = stream or sys.stderr
        self.quiet = quiet
        self.style = Style(use_color(self.stream, color))
        self.tty = isatty(self.stream)
        self.uni = unicode_ok(self.stream)
        self._status_on = False

    def _print(self, text: str) -> None:
        self.end_status()
        print(text, file=self.stream, flush=True)

    def info(self, msg: str) -> None:
        if not self.quiet:
            self._print(msg)

    def hint(self, msg: str) -> None:
        if not self.quiet:
            self._print(self.style(msg, "dim"))

    def success(self, msg: str) -> None:
        if not self.quiet:
            self._print(self.style(("✓ " if self.uni else "OK ") + msg, "green"))

    def warn(self, msg: str) -> None:
        self._print(self.style(("! " if self.uni else "! ") + msg, "yellow"))

    def error(self, msg: str) -> None:
        self._print(self.style(("✗ " if self.uni else "x ") + msg, "red", "bold"))

    def status(self, msg: str) -> None:
        if self.quiet or not self.tty:
            return
        cols = shutil.get_terminal_size((80, 20)).columns
        self.stream.write("\r\x1b[2K" + truncate(msg, cols - 1) if self.style.enabled else "\r" + pad(truncate(msg, cols - 1), cols - 1))
        self.stream.flush()
        self._status_on = True

    def end_status(self) -> None:
        if self._status_on:
            self.stream.write("\r\x1b[2K" if self.style.enabled else "\r" + " " * (shutil.get_terminal_size((80, 20)).columns - 1) + "\r")
            self.stream.flush()
            self._status_on = False


class NullUI(UI):
    """A UI that prints nothing (the default when used as a library)."""

    def __init__(self) -> None:
        self.stream = sys.stderr
        self.quiet = True
        self.style = Style(False)
        self.tty = False
        self.uni = True
        self._status_on = False

    def _print(self, text: str) -> None:
        pass


def page(text: str, use_pager: bool = True) -> None:
    """Show through less -R when longer than the screen, otherwise print directly."""
    out = sys.stdout
    if use_pager and isatty(out) and os.name != "nt":
        rows = shutil.get_terminal_size((80, 24)).lines
        if text.count("\n") >= rows - 1:
            pager = os.environ.get("PAGER")
            cmd = None
            if pager and shutil.which(pager.split()[0]):
                cmd = pager
            elif shutil.which("less"):
                cmd = "less -R -F -X"
            if cmd:
                env = dict(os.environ, LESSCHARSET="utf-8")
                try:
                    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, env=env)
                    try:
                        p.communicate(text.encode("utf-8"))
                    except BrokenPipeError:
                        pass
                    return
                except OSError:
                    pass
    write_stdout(text)


def write_stdout(text: str) -> None:
    """Write text to a TTY, but always UTF-8 bytes when piped or redirected."""
    try:
        if isatty(sys.stdout) or not hasattr(sys.stdout, "buffer"):
            sys.stdout.write(text)
        else:
            sys.stdout.flush()
            sys.stdout.buffer.write(text.encode("utf-8"))
        sys.stdout.flush()
    except BrokenPipeError:  # pipe closed early, e.g. `| head`
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
