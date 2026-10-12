"""Claude 공유 링크(claude.ai/share/…)에서 사용자 입력과 에이전트 출력을 추출합니다.

라이브러리로 쓸 때::

    from claude_share_extract import load_snapshot_file, extract, export

    snap = load_snapshot_file("snapshot.json")
    conv = extract(snap)
    print(export([conv], "jsonl"))
"""

__version__ = "0.2.0"

from .snapshot import (  # noqa: E402
    NotAShareLink,
    SnapshotError,
    load_snapshot_file,
    parse_snapshot_text,
    share_id_from,
    share_page_url,
    snapshot_api_url,
)
from .extract import Options, extract  # noqa: E402
from .select import select_turns  # noqa: E402
from .exporters import FORMATS, export  # noqa: E402
from .bundle import write_bundle  # noqa: E402
from .audit import verify as verify_bundle  # noqa: E402
from .chatgpt import (  # noqa: E402
    capture_and_extract,
    capture_chatgpt,
    extract_chatgpt,
    validate_chatgpt_url,
)

__all__ = [
    "__version__",
    "NotAShareLink",
    "SnapshotError",
    "load_snapshot_file",
    "parse_snapshot_text",
    "share_id_from",
    "share_page_url",
    "snapshot_api_url",
    "Options",
    "extract",
    "select_turns",
    "FORMATS",
    "export",
    "write_bundle",
    "verify_bundle",
    "capture_chatgpt",
    "extract_chatgpt",
    "capture_and_extract",
    "validate_chatgpt_url",
]
