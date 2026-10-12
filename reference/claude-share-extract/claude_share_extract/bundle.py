"""대화를 손실 없는 번들 디렉터리로 기록합니다 (provider 중립).

하나의 번들에는 원본 바이트, 정규화된 conversation.json, (호출자가 주면) transcript,
아티팩트의 모든 버전, 에셋 메타데이터와 파일, manifest.json, audit.json,
checksums.sha256 이 들어갑니다. 가져오지 못한 항목은 manifest 의 dropped/uncertain 에
이유와 함께 남깁니다.

이 모듈은 Claude provider 전용 구조를 가정하지 않습니다. ChatGPT provider 도
같은 ``conversation`` 모양(source/turns/messages/branches/artifacts/stats)과
``extra_files`` (예: page.html, screenshot.png) 로 그대로 쓸 수 있습니다.
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
    """경로 구분자·제어문자·.. 를 제거한 안전한 단일 파일명."""
    s = _UNSAFE.sub("_", str(name if name is not None else "")).strip().strip(". ")
    s = s.replace("..", "_")
    if not s:
        return fallback
    return s[:120]


def _safe_rel(rel: str) -> str:
    """상대 경로를 번들 안으로 가둡니다 (앞의 /, .. 제거)."""
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
    """같은 디렉터리 안에서 파일명 충돌을 피합니다."""

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
    """번들을 ``dest`` 디렉터리에 쓰고 manifest dict 를 돌려줍니다.

    원본 ``conversation`` dict 는 변경하지 않습니다.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    # provider 는 top-level 또는 source 아래에 올 수 있음 (Claude vs ChatGPT 스키마)
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
        # 바이트로 직접 써서 플랫폼별 개행 변환을 막습니다 (해시 일관성).
        with open(path, "wb") as f:
            f.write(raw)
        collected[rel] = raw
        return rel

    # 1) 원본 바이트 (verbatim)
    if raw_source is not None:
        put(_safe_name(raw_name, "raw.json"), raw_source)
    else:
        manifest_uncertain.append({"item": "raw source", "reason": "호출자가 원본 스냅샷/페이지 바이트를 주지 않음"})

    # 2) 정규화된 conversation.json (내부용 _키 제외, 원본 미변경)
    conv_public = {k: v for k, v in conversation.items() if not str(k).startswith("_")}
    conv_public.setdefault("provider", provider)
    put("conversation.json", json.dumps(conv_public, ensure_ascii=False, indent=2, default=str) + "\n")

    # 3) transcript (호출자가 주면)
    if transcript is not None:
        put(_safe_name(transcript_name, "transcript.md"), transcript)
    else:
        manifest_uncertain.append({"item": "transcript", "reason": "호출자가 transcript 를 주지 않음"})

    # 4) 아티팩트의 모든 버전
    artifact_summaries: List[Dict[str, Any]] = []
    for art in conversation.get("artifacts") or []:
        if not isinstance(art, dict):
            continue
        key = art.get("key") or art.get("title") or "artifact"
        ext = str(art.get("ext") or "txt")
        dir_name = namer.unique("artifacts", _safe_name(key, "artifact"))
        base_dir = f"artifacts/{dir_name}"
        # history(=Claude) 또는 versions 리스트(=ChatGPT) 어느 쪽이든 모든 버전을 보존.
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

    # 5) 에셋 (이미지·파일 등) — 바이트가 있으면 저장, 없으면 메타데이터만 + dropped
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
            reason = asset.get("reason") or "에셋 바이트를 받지 못함 (공유 스냅샷에 내용 없음 또는 인증 필요)"
            manifest_dropped.append({"item": f"asset:{asset.get('name') or asset.get('id')}", "reason": reason})
        asset_summaries.append(summary)

    # 6) provider 전용 추가 파일 (예: page.html, screenshot.png)
    for rel, data in (extra_files or {}).items():
        put(rel, data)

    # 7) manifest.json — branches 는 dict(Claude) 또는 list(ChatGPT) 둘 다 허용
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
        # 지금까지 쓴 데이터 파일 + 곧 쓸 manifest.json 자신 (audit/checksums 는 제외)
        "contents": sorted(collected) + ["manifest.json"],
        "dropped": manifest_dropped,
        "uncertain": manifest_uncertain,
        "limitations": list(limitations) if limitations is not None else [
            "숨은 reasoning 이나 서버가 공유 페이지로 보내지 않은 비공개 데이터는 가져올 수 없습니다.",
            "공유 스냅샷에는 공유 시점까지의 메시지만 있고, 바이너리 첨부 원본이 없을 수 있습니다.",
        ],
    }
    put("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n")

    # 8) audit.json — 지금까지 쓴 모든 파일의 바이트 기준 SHA-256
    audit = build_audit(collected, provider=provider, source=source,
                        exported_at=manifest["generatedAt"])
    (dest / "audit.json").write_bytes(
        (json.dumps(audit, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))

    # 9) checksums.sha256 — 표준 sha256sum 형식 (audit/checksums 자신은 제외)
    lines = [f"{sha256_bytes(collected[rel])}  {rel}\n" for rel in sorted(collected)]
    (dest / "checksums.sha256").write_bytes("".join(lines).encode("utf-8"))

    return manifest
