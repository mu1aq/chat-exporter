"""Write a conversation to a lossless bundle directory (provider-neutral).

One bundle contains the raw bytes, the normalized conversation.json, the
transcript (when the caller supplies one), every version of each artifact,
asset metadata and files, manifest.json, audit.json and checksums.sha256.
Items that could not be fetched are listed in the manifest's dropped/uncertain
with a reason.

This module assumes no Claude-specific structure. The ChatGPT provider can use
it as-is with the same ``conversation`` shape
(source/turns/messages/branches/artifacts/stats) and ``extra_files``
(e.g. page.html, screenshot.png).
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from . import __version__
from .audit import build_audit, sha256_bytes

Bytesish = Union[bytes, bytearray, str]

_UNSAFE = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')


def _as_bytes(data: Bytesish) -> bytes:
    if isinstance(data, str):
        return data.encode("utf-8")
    return bytes(data)


def _safe_name(name: Any, fallback: str = "item") -> str:
    """A safe single filename with path separators, control chars and .. removed."""
    s = _UNSAFE.sub("_", str(name if name is not None else "")).strip().strip(". ")
    s = s.replace("..", "_")
    if not s:
        return fallback
    return s[:120]


def _safe_rel(rel: str) -> str:
    """Confine a relative path inside the bundle (strip leading /, drop ..)."""
    parts = []
    for seg in str(rel).replace("\\", "/").split("/"):
        seg = seg.strip()
        if not seg or seg == ".":
            continue
        if seg == "..":
            continue
        parts.append(_safe_name(seg, "part"))
    return "/".join(parts) or "file"


class _Namer:
    """Avoid filename collisions within the same directory."""

    def __init__(self) -> None:
        self._used: Dict[str, set] = {}

    def unique(self, directory: str, name: str) -> str:
        used = self._used.setdefault(directory, set())
        if name.lower() not in used:
            used.add(name.lower())
            return name
        p = Path(name)
        stem, ext = p.stem, p.suffix
        i = 1
        while True:
            cand = f"{stem}_{i}{ext}"
            if cand.lower() not in used:
                used.add(cand.lower())
                return cand
            i += 1


def write_bundle(
    dest: Union[str, Path],
    conversation: Dict[str, Any],
    *,
    raw_source: Optional[Bytesish] = None,
    raw_name: str = "raw.json",
    transcript: Optional[str] = None,
    transcript_name: str = "transcript.md",
    assets: Optional[List[Dict[str, Any]]] = None,
    provider: Optional[str] = None,
    dropped: Optional[List[Dict[str, Any]]] = None,
    uncertain: Optional[List[Dict[str, Any]]] = None,
    limitations: Optional[List[str]] = None,
    extra_files: Optional[Mapping[str, Bytesish]] = None,
) -> Dict[str, Any]:
    """Write the bundle into the ``dest`` directory and return the manifest dict.

    The original ``conversation`` dict is not modified.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    # provider may sit at top level or under source (Claude vs ChatGPT schema)
    provider = (provider or conversation.get("provider")
                or (conversation.get("source") or {}).get("provider") or "claude")

    namer = _Namer()
    collected: Dict[str, bytes] = {}
    manifest_dropped: List[Dict[str, Any]] = list(dropped or [])
    manifest_uncertain: List[Dict[str, Any]] = list(uncertain or [])

    def put(rel: str, data: Bytesish) -> str:
        rel = _safe_rel(rel)
        raw = _as_bytes(data)
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write bytes directly to avoid platform newline translation (hash consistency).
        with open(path, "wb") as f:
            f.write(raw)
        collected[rel] = raw
        return rel

    # 1) raw bytes (verbatim)
    if raw_source is not None:
        put(_safe_name(raw_name, "raw.json"), raw_source)
    else:
        manifest_uncertain.append({"item": "raw source", "reason": "caller did not provide raw snapshot/page bytes"})

    # 2) normalized conversation.json (exclude internal _keys, original unchanged)
    conv_public = {k: v for k, v in conversation.items() if not str(k).startswith("_")}
    conv_public.setdefault("provider", provider)
    put("conversation.json", json.dumps(conv_public, ensure_ascii=False, indent=2, default=str) + "\n")

    # 3) transcript (when the caller supplies one)
    if transcript is not None:
        put(_safe_name(transcript_name, "transcript.md"), transcript)
    else:
        manifest_uncertain.append({"item": "transcript", "reason": "caller did not provide a transcript"})

    # 4) every version of each artifact
    artifact_summaries: List[Dict[str, Any]] = []
    for art in conversation.get("artifacts") or []:
        if not isinstance(art, dict):
            continue
        key = art.get("key") or art.get("title") or "artifact"
        ext = str(art.get("ext") or "txt")
        dir_name = namer.unique("artifacts", _safe_name(key, "artifact"))
        base_dir = f"artifacts/{dir_name}"
        # Preserve every version, whether from history (Claude) or a versions list (ChatGPT).
        history = art.get("history")
        if not history:
            versions = art.get("versions")
            if isinstance(versions, list):
                history = versions
            else:
                history = [{"version": versions if isinstance(versions, int) else 1,
                            "action": "create", "content": art.get("content", ""), "ext": ext}]
        version_files: List[Dict[str, Any]] = []
        for entry in history:
            entry = entry if isinstance(entry, dict) else {"content": entry}
            vext = str(entry.get("ext") or ext)
            vnum = entry.get("version")
            if not isinstance(vnum, int):
                vnum = len(version_files) + 1
            fname = namer.unique(base_dir, f"v{vnum:02d}.{vext}")
            rel = put(f"{base_dir}/{fname}", entry.get("content", ""))
            version_files.append({"version": vnum, "action": entry.get("action"), "path": rel,
                                  "sha256": sha256_bytes(collected[rel])})
        latest_name = namer.unique(base_dir, f"latest.{ext}")
        latest_rel = put(f"{base_dir}/{latest_name}", art.get("content", ""))
        meta = {k: art.get(k) for k in ("key", "title", "type", "language", "ext", "versions")}
        meta["versionFiles"] = version_files
        meta["latest"] = latest_rel
        put(f"{base_dir}/meta.json", json.dumps(meta, ensure_ascii=False, indent=2, default=str) + "\n")
        artifact_summaries.append({"key": art.get("key"), "title": art.get("title"), "dir": base_dir,
                                   "versions": art.get("versions"), "versionCount": len(version_files)})

    # 5) assets (images, files, etc.) — save bytes when present, else metadata only + dropped
    asset_summaries: List[Dict[str, Any]] = []
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        name = _safe_name(asset.get("name") or asset.get("id") or "asset", "asset")
        data = asset.get("data")
        if data is None and isinstance(asset.get("content_base64"), str):
            try:
                data = base64.b64decode(asset["content_base64"])
            except (ValueError, TypeError):
                data = None
        summary = {
            "id": asset.get("id"),
            "name": asset.get("name"),
            "mime": asset.get("mime"),
            "url": asset.get("url"),
            "source": asset.get("source"),
            "fetched": False,
            "saved_path": None,
            "sha256": asset.get("sha256"),
        }
        if data is not None:
            fname = namer.unique("assets", name)
            rel = put(f"assets/{fname}", data)
            summary["fetched"] = True
            summary["saved_path"] = rel
            summary["sha256"] = sha256_bytes(collected[rel])
            summary["bytes"] = len(collected[rel])
        else:
            reason = asset.get("reason") or "asset bytes not received (not in the share snapshot, or authentication required)"
            manifest_dropped.append({"item": f"asset:{asset.get('name') or asset.get('id')}", "reason": reason})
        asset_summaries.append(summary)

    # 6) provider-specific extra files (e.g. page.html, screenshot.png)
    for rel, data in (extra_files or {}).items():
        put(rel, data)

    # 7) manifest.json — branches may be a dict (Claude) or a list (ChatGPT)
    raw_branches = conversation.get("branches")
    if isinstance(raw_branches, dict):
        branch_paths = raw_branches.get("paths") or []
        active_leaf = raw_branches.get("active_leaf_uuid")
        branch_linked = raw_branches.get("linked")
    elif isinstance(raw_branches, list):
        branch_paths = raw_branches
        active_leaf = conversation.get("active_branch_id")
        branch_linked = None
    else:
        branch_paths, active_leaf, branch_linked = [], None, None
    source = conversation.get("source") or {}
    manifest: Dict[str, Any] = {
        "schemaVersion": 1,
        "tool": {"name": "shared-chat-exporter", "version": __version__},
        "provider": provider,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "stats": conversation.get("stats"),
        "branches": {
            "active_leaf_uuid": active_leaf,
            "linked": branch_linked,
            "pathCount": len(branch_paths),
            "alternateCount": sum(1 for p in branch_paths if isinstance(p, dict) and not p.get("is_active")),
        },
        "artifacts": artifact_summaries,
        "artifactEvents": conversation.get("artifact_events") or [],
        "assets": asset_summaries,
        "warnings": conversation.get("warnings") or [],
        # data files written so far + manifest.json itself (audit/checksums excluded)
        "contents": sorted(collected) + ["manifest.json"],
        "dropped": manifest_dropped,
        "uncertain": manifest_uncertain,
        "limitations": list(limitations) if limitations is not None else [
            "Hidden reasoning or private data the server did not send to the share page cannot be retrieved.",
            "A share snapshot holds only messages up to the share time and may lack original binary attachments.",
        ],
    }
    put("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n")

    # 8) audit.json — byte-level SHA-256 of every file written so far
    audit = build_audit(collected, provider=provider, source=source,
                        exported_at=manifest["generatedAt"])
    (dest / "audit.json").write_bytes(
        (json.dumps(audit, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))

    # 9) checksums.sha256 — standard sha256sum format (audit/checksums themselves excluded)
    lines = [f"{sha256_bytes(collected[rel])}  {rel}\n" for rel in sorted(collected)]
    (dest / "checksums.sha256").write_bytes("".join(lines).encode("utf-8"))

    return manifest
