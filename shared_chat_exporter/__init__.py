"""Unified exporter for public Claude and ChatGPT shares.

Library usage::

    from shared_chat_exporter import load_snapshot_file, extract, export

    snap = load_snapshot_file("snapshot.json")
    conv = extract(snap)
    print(export([conv], "jsonl"))

For ChatGPT pages use :func:`capture_and_extract`, which drives a browser and
returns the same conversation shape.
"""

__version__ = "0.3.0"

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
    ChatGPTBrowserUnavailable,
    ChatGPTError,
    capture_and_extract,
    capture_chatgpt,
    chatgpt_share_id,
    extract_chatgpt,
    validate_chatgpt_url,
)
from .router import Route, detect_provider, route_url, routes_from_args  # noqa: E402

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
    "ChatGPTBrowserUnavailable",
    "ChatGPTError",
    "capture_and_extract",
    "capture_chatgpt",
    "chatgpt_share_id",
    "extract_chatgpt",
    "validate_chatgpt_url",
    "Route",
    "detect_provider",
    "route_url",
    "routes_from_args",
]
