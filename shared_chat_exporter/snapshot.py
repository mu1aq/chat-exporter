"""Share-link parsing and snapshot JSON reading.

A claude.ai share page does not contain the conversation directly; when the
page opens it fetches JSON from ``/api/chat_snapshots/<share ID>``. That
endpoint is an undocumented internal API, so its format may change.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlsplit

API_BASE = os.environ.get("CSE_API_BASE", "https://claude.ai").rstrip("/")
SNAPSHOT_PATH = "/api/chat_snapshots/{id}?rendering_mode=messages&render_all_tools=true"

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_HOSTS = {"claude.ai", urlsplit(API_BASE).netloc.lower()}
_ID_RE = re.compile(r"[A-Za-z0-9-]+")
_PRIVATE_SEGMENTS = {"chat", "project", "new", "recents", "projects"}


class SnapshotError(ValueError):
    """Raised when the input is not snapshot JSON or cannot be read."""


class NotAShareLink(ValueError):
    """Raised when the input is not a Claude share link."""


def share_id_from(value: str) -> str:
    """Extract the share ID from a share link, snapshot API URL, or the ID itself."""
    s = str(value or "").strip().strip("<>\"'")
    if re.fullmatch(_UUID, s):
        return s.lower()
    url = s if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", s) else "https://" + s
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").lower()
        netloc = parts.netloc.lower()
    except ValueError:
        host = netloc = ""
    host = host[4:] if host.startswith("www.") else host
    if host in _HOSTS or netloc in _HOSTS:
        segs = [x for x in parts.path.split("/") if x]
        if len(segs) >= 2 and segs[0] == "share" and _ID_RE.fullmatch(segs[1]):
            return segs[1]
        if len(segs) >= 3 and segs[:2] == ["api", "chat_snapshots"] and _ID_RE.fullmatch(segs[2]):
            return segs[2]
        if segs and segs[0] in _PRIVATE_SEGMENTS:
            raise NotAShareLink(
                "This is a private conversation URL. Use a claude.ai/share/… link created with the 'Share' button."
            )
    raise NotAShareLink(f"Not a Claude share link: {s[:80]}")


def is_share_ref(value: str) -> bool:
    try:
        share_id_from(value)
        return True
    except NotAShareLink:
        return False


def snapshot_api_url(share_id: str) -> str:
    return API_BASE + SNAPSHOT_PATH.format(id=share_id)


def snapshot_api_path(share_id: str) -> str:
    return SNAPSHOT_PATH.format(id=share_id)


def share_page_url(share_id: str) -> str:
    return f"{API_BASE}/share/{share_id}"


def parse_snapshot_text(text: str) -> Dict[str, Any]:
    """Read snapshot JSON text.

    A full browser copy can add text such as 'Pretty-print' around the JSON,
    so only the span from the first ``{`` to the last ``}`` is used.
    """
    s = str(text or "").lstrip("﻿")
    a, b = s.find("{"), s.rfind("}")
    if a < 0:
        raise SnapshotError("No JSON found. Check that you copied the entire snapshot page.")
    if b <= a:
        raise SnapshotError("The JSON is truncated. Copy or save the whole page again.")
    try:
        data = json.loads(s[a : b + 1])
    except json.JSONDecodeError as e:
        raise SnapshotError(f"Invalid JSON ({e.msg}, line {e.lineno}). Only part may have been copied.") from e
    if isinstance(data, dict) and data.get("type") == "error" and data.get("error"):
        err = data["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise SnapshotError(f"Claude returned an error: {msg}")
    if not isinstance(data, dict) or not isinstance(data.get("chat_messages"), list):
        raise SnapshotError("No chat_messages. Check that this is Claude share snapshot JSON.")
    return data


def decode_bytes(raw: bytes) -> str:
    """Accept both UTF-8 (with BOM) and UTF-16 (Windows PowerShell redirection)."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def read_text_file(path: os.PathLike | str) -> str:
    return decode_bytes(Path(path).read_bytes())


def load_snapshot_file(path: os.PathLike | str) -> Dict[str, Any]:
    return parse_snapshot_text(read_text_file(path))


def snapshot_matches(snap: Dict[str, Any], share_id: str) -> bool:
    uid = snap.get("uuid")
    return not uid or str(uid).lower() == share_id.lower()
