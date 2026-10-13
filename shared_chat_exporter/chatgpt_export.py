"""Read a ChatGPT account data export (no browser).

The export is a ``.zip`` containing ``conversations.json`` (also accepted on its
own): a list of conversations, each a ``mapping`` tree of message nodes. One file
yields many conversations. Each conversation's active path (``current_node`` to
root) is turned into a Claude-snapshot-shaped dict and handed to :func:`extract`.
"""

from __future__ import annotations

import base64
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from .extract import ROOT_PARENT
from .snapshot import SnapshotError

_EXPORT_NAME = "conversations.json"
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")


def detect_chatgpt_export(path: Union[str, Path]) -> bool:
    """True if ``path`` is a ChatGPT data export (a zip with conversations.json, or that file)."""
    path = Path(path)
    if path.name == _EXPORT_NAME:
        return True
    if path.suffix.lower() == ".zip" and zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as zf:
                return any(Path(n).name == _EXPORT_NAME for n in zf.namelist())
        except (OSError, zipfile.BadZipFile):
            return False
    return False


def _load_export(path: Path) -> List[Dict[str, Any]]:
    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                name = next(n for n in zf.namelist() if Path(n).name == _EXPORT_NAME)
                data = json.loads(zf.read(name).decode("utf-8"))
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, zipfile.BadZipFile, ValueError, StopIteration) as e:
        raise SnapshotError(f"Could not read ChatGPT export: {e}") from e
    if isinstance(data, dict) and "mapping" in data:
        return [data]
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict) and isinstance(c.get("mapping"), dict)]
    raise SnapshotError("ChatGPT export has no conversations (expected a list with a 'mapping').")


def iter_export_conversations(path: Union[str, Path]) -> Iterator[Dict[str, Any]]:
    yield from _load_export(Path(path))


def zip_asset_index(path: Union[str, Path]) -> List[Tuple[str, bytes]]:
    """Image files inside an export zip, as (member name, bytes). Empty for a bare json."""
    path = Path(path)
    if path.suffix.lower() != ".zip" or not zipfile.is_zipfile(path):
        return []
    out: List[Tuple[str, bytes]] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for n in zf.namelist():
                if n.endswith("/") or Path(n).name == _EXPORT_NAME:
                    continue
                if Path(n).suffix.lower() in _IMAGE_EXTS:
                    out.append((n, zf.read(n)))
    except (OSError, zipfile.BadZipFile):
        return []
    return out


def _pointer_id(pointer: Any) -> Optional[str]:
    if not isinstance(pointer, str) or "://" not in pointer:
        return None
    tail = pointer.split("://", 1)[1].strip("/")
    return tail.split("/")[-1] or None


def _mime_for(name: str) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    return "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext or 'png'}"


def _collect_images(m: Dict[str, Any], index: List[Tuple[str, bytes]], seen: set) -> List[Dict[str, Any]]:
    content = m.get("content")
    if not isinstance(content, dict):
        return []
    attach = {a.get("id"): a for a in (m.get("metadata") or {}).get("attachments") or [] if isinstance(a, dict)}
    out: List[Dict[str, Any]] = []
    for part in content.get("parts") or []:
        if not (isinstance(part, dict) and part.get("content_type") == "image_asset_pointer"):
            continue
        fid = _pointer_id(part.get("asset_pointer"))
        if not fid or fid in seen:
            continue
        seen.add(fid)
        meta = attach.get(fid, {})
        hit = next((data for n, data in index if fid in n), None)
        name = meta.get("name") or (f"{fid}.png")
        asset: Dict[str, Any] = {"id": fid, "name": name,
                                 "mime": meta.get("mime_type") or meta.get("mimeType") or _mime_for(name),
                                 "source": "chatgpt-export"}
        if hit is not None:
            asset["content_base64"] = base64.b64encode(hit).decode("ascii")
        else:
            asset["reason"] = "image bytes not in the export (bare conversations.json or missing file)"
        out.append(asset)
    return out


def _iso(epoch: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _parts_text(content: Any) -> str:
    if not isinstance(content, dict):
        return ""
    if isinstance(content.get("text"), str):  # code / execution_output
        return content["text"]
    return "\n".join(p for p in (content.get("parts") or []) if isinstance(p, str))


def _active_messages(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    mapping = raw.get("mapping") or {}
    cur = raw.get("current_node")
    msgs: List[Dict[str, Any]] = []
    if cur and cur in mapping:
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            node = mapping.get(cur) or {}
            if isinstance(node.get("message"), dict):
                msgs.append(node["message"])
            cur = node.get("parent")
        msgs.reverse()
    else:  # no current_node: fall back to create_time order
        nodes = [n["message"] for n in mapping.values()
                 if isinstance(n, dict) and isinstance(n.get("message"), dict)]
        msgs = sorted(nodes, key=lambda m: m.get("create_time") or 0)
    return msgs


def export_to_snapshot(raw: Dict[str, Any], assets_index: Optional[List[Tuple[str, bytes]]] = None) -> Dict[str, Any]:
    """Turn one exported ChatGPT conversation into a Claude-snapshot-shaped dict.

    ``assets_index`` (from :func:`zip_asset_index`) supplies image bytes to save.
    """
    index = assets_index or []
    messages: List[Dict[str, Any]] = []
    assets: List[Dict[str, Any]] = []
    seen: set = set()
    for m in _active_messages(raw):
        role = (m.get("author") or {}).get("role")
        if role in ("system", "tool"):  # scaffolding / plugin output, not a turn
            continue
        if (m.get("metadata") or {}).get("is_visually_hidden_from_conversation"):
            continue
        assets.extend(_collect_images(m, index, seen))
        text = _parts_text(m.get("content"))
        if not text.strip():
            continue
        i = len(messages)
        messages.append({
            "uuid": f"m-{i}",
            "parent_message_uuid": messages[-1]["uuid"] if messages else ROOT_PARENT,
            "index": i,
            "sender": "human" if role == "user" else "assistant",
            "created_at": _iso(m.get("create_time")),
            "content": [{"type": "text", "text": text}],
        })
    snap: Dict[str, Any] = {
        "uuid": raw.get("conversation_id") or raw.get("id") or "conversation",
        "name": raw.get("title") or "",
        "created_at": _iso(raw.get("create_time")),
        "updated_at": _iso(raw.get("update_time")),
        "chat_messages": messages,
    }
    if assets:
        snap["_assets"] = assets
    return snap


def finalize_export(conv: Dict[str, Any], path: Union[str, Path], snap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    src = conv["source"]
    src["provider"] = "chatgpt"
    src["share_url"] = None
    src["export_file"] = str(path)
    if not src.get("title"):
        src["title"] = "ChatGPT conversation"
    conv["provider"] = "chatgpt"
    if snap and snap.get("_assets"):
        conv.setdefault("assets", []).extend(snap["_assets"])
    return conv
