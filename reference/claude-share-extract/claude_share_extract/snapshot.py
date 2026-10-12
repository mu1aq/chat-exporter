"""공유 링크 해석과 스냅샷 JSON 읽기.

claude.ai 공유 페이지는 대화 내용을 직접 담고 있지 않고, 페이지가 열릴 때
``/api/chat_snapshots/<공유 ID>`` 에서 JSON으로 받아옵니다. 이 엔드포인트는
공개 문서가 없는 내부 API라서 형식이 바뀔 수 있습니다.
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
    """스냅샷 JSON이 아니거나 읽을 수 없을 때."""


class NotAShareLink(ValueError):
    """입력이 Claude 공유 링크가 아닐 때."""


def share_id_from(value: str) -> str:
    """공유 링크, 스냅샷 API 주소, 또는 공유 ID 자체에서 공유 ID를 꺼냅니다."""
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
                "비공개 대화 주소입니다. 대화 화면의 '공유' 버튼으로 만든 claude.ai/share/… 링크를 쓰세요."
            )
    raise NotAShareLink(f"Claude 공유 링크가 아닙니다: {s[:80]}")


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
    """스냅샷 JSON 텍스트를 읽습니다.

    브라우저에서 전체 복사하면 JSON 앞뒤에 'Pretty-print' 같은 글자가 붙을 수
    있어서, 첫 ``{`` 부터 마지막 ``}`` 까지만 씁니다.
    """
    s = str(text or "").lstrip("﻿")
    a, b = s.find("{"), s.rfind("}")
    if a < 0:
        raise SnapshotError("JSON을 찾지 못했습니다. 스냅샷 페이지 전체를 복사했는지 확인하세요.")
    if b <= a:
        raise SnapshotError("JSON이 중간에 잘렸습니다. 페이지 전체를 다시 복사하거나 저장하세요.")
    try:
        data = json.loads(s[a : b + 1])
    except json.JSONDecodeError as e:
        raise SnapshotError(f"JSON 형식이 올바르지 않습니다 ({e.msg}, {e.lineno}행). 일부만 복사됐을 수 있습니다.") from e
    if isinstance(data, dict) and data.get("type") == "error" and data.get("error"):
        err = data["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise SnapshotError(f"Claude가 오류를 돌려줬습니다: {msg}")
    if not isinstance(data, dict) or not isinstance(data.get("chat_messages"), list):
        raise SnapshotError("chat_messages가 없습니다. Claude 공유 스냅샷 JSON이 맞는지 확인하세요.")
    return data


def decode_bytes(raw: bytes) -> str:
    """UTF-8(BOM 포함)과 UTF-16(Windows PowerShell 리디렉션)을 모두 받습니다."""
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
