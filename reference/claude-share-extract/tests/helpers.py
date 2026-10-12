import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

BASIC_ID = "3b8f2c1e-5a6d-4e7f-9a0b-1c2d3e4f5a6b"
RICH_ID = "5f2c1a9e-1111-4c2d-9e8f-abcdefabcdef"
API_ID = "9d0e1f2a-3b4c-4d5e-8f6a-7b8c9d0e1f2a"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture(name: str) -> dict:
    return json.loads(fixture_text(name))


class _Bytes(io.BytesIO):
    pass


class Captured:
    def __init__(self):
        self.out = ""
        self.err = ""
        self.code = None


@contextlib.contextmanager
def capture(stdin_text: str = ""):
    """stdout/stderr/stdin 을 바꿔 끼우고 CLI를 실행합니다 (stdout은 바이트 버퍼 포함)."""
    cap = Captured()
    out_buf = io.BytesIO()
    out = io.TextIOWrapper(out_buf, encoding="utf-8", newline="")
    err = io.StringIO()
    inp = io.TextIOWrapper(io.BytesIO(stdin_text.encode("utf-8")), encoding="utf-8")
    old = sys.stdout, sys.stderr, sys.stdin
    sys.stdout, sys.stderr, sys.stdin = out, err, inp
    try:
        yield cap
    finally:
        out.flush()
        sys.stdout, sys.stderr, sys.stdin = old
        cap.out = out_buf.getvalue().decode("utf-8")
        cap.err = err.getvalue()


def run_cli(*argv, stdin_text=""):
    from claude_share_extract.cli import main

    with capture(stdin_text) as cap:
        cap.code = main(list(argv))
    return cap


class TempDir:
    def __enter__(self):
        self._td = tempfile.TemporaryDirectory()
        return Path(self._td.name)

    def __exit__(self, *a):
        self._td.cleanup()


os.environ.setdefault("NO_COLOR", "1")
