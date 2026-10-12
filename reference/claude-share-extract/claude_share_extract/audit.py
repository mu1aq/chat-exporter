"""번들 무결성 감사 보고서와 검증 (provider 중립).

감사 보고서는 저장된 각 파일의 **바이트 기준** SHA-256과 크기를 기록합니다.
``verify`` 는 디스크의 실제 파일에서 SHA-256을 다시 계산해 보고서와 대조하고,
보고서 자체의 스키마도 검사합니다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from . import __version__

SCHEMA_VERSION = 1
TOOL = {"name": "shared-chat-exporter", "version": __version__}

LIMITATIONS = [
    "이 보고서는 저장된 파일 바이트가 내보낸 뒤 바뀌지 않았음을 증명합니다. "
    "공유 페이지가 원본 대화의 모든 토큰을 노출했다는 증명은 아닙니다.",
    "스냅샷·공유 페이지 형식은 공개·고정된 내보내기 API가 아니므로 예고 없이 바뀔 수 있습니다.",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Union[str, Path]) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_audit(
    files: Mapping[str, bytes],
    *,
    provider: Optional[str] = None,
    source: Optional[Dict[str, Any]] = None,
    exported_at: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """``files`` = {상대경로: 바이트}. 각 파일의 크기·SHA-256(bytes)을 기록합니다."""
    entries: List[Dict[str, Any]] = []
    for rel in sorted(files):
        data = files[rel]
        entries.append({"path": rel, "bytes": len(data), "sha256": sha256_bytes(data)})
    audit: Dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "tool": dict(TOOL),
        "provider": provider,
        "source": source or {},
        "exportedAt": exported_at,
        "fileCount": len(entries),
        "files": entries,
        "limitations": list(LIMITATIONS),
    }
    if extra:
        audit.update(extra)
    return audit


_REQUIRED = (("schemaVersion", int), ("tool", dict), ("files", list))


def validate_schema(audit: Any) -> List[str]:
    """감사 보고서의 구조를 검사하고 문제 목록을 돌려줍니다 (빈 목록 = 정상)."""
    errs: List[str] = []
    if not isinstance(audit, dict):
        return ["audit가 객체(JSON object)가 아님"]
    for key, typ in _REQUIRED:
        if key not in audit:
            errs.append(f"필수 키 누락: {key}")
        elif not isinstance(audit[key], typ):
            errs.append(f"{key} 타입 오류: {type(audit[key]).__name__}")
    if "schemaVersion" in audit and audit["schemaVersion"] != SCHEMA_VERSION:
        errs.append(f"schemaVersion 불일치: {audit.get('schemaVersion')} (지원 {SCHEMA_VERSION})")
    files = audit.get("files")
    if isinstance(files, list):
        seen = set()
        for i, e in enumerate(files):
            if not isinstance(e, dict):
                errs.append(f"files[{i}]가 객체가 아님")
                continue
            for k, typ in (("path", str), ("sha256", str), ("bytes", int)):
                if k not in e:
                    errs.append(f"files[{i}].{k} 누락")
                elif not isinstance(e[k], typ):
                    errs.append(f"files[{i}].{k} 타입 오류")
            path = e.get("path")
            if isinstance(path, str):
                if path in seen:
                    errs.append(f"중복 경로: {path}")
                seen.add(path)
            if isinstance(e.get("sha256"), str) and len(e["sha256"]) != 64:
                errs.append(f"files[{i}].sha256 길이 오류")
    return errs


def verify(audit: Union[Dict[str, Any], str, Path], base_dir: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """감사 보고서(dict 또는 audit.json 경로)의 각 파일을 ``base_dir`` 에서 바이트 기준으로 재검증합니다.

    반환: {ok, checked, mismatches, missing, schema_errors}.
    """
    if not isinstance(audit, dict):
        audit_path = Path(audit)
        if base_dir is None:
            base_dir = audit_path.parent
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    base = Path(base_dir) if base_dir is not None else Path(".")

    schema_errors = validate_schema(audit)
    mismatches: List[Dict[str, Any]] = []
    missing: List[str] = []
    checked: List[str] = []
    for e in audit.get("files") or []:
        if not isinstance(e, dict) or not isinstance(e.get("path"), str):
            continue
        rel = e["path"]
        p = base / rel
        if not p.is_file():
            missing.append(rel)
            continue
        actual = sha256_file(p)
        checked.append(rel)
        if actual != e.get("sha256"):
            mismatches.append({"path": rel, "expected": e.get("sha256"), "actual": actual})
    ok = not schema_errors and not mismatches and not missing
    return {"ok": ok, "checked": checked, "mismatches": mismatches,
            "missing": missing, "schema_errors": schema_errors}
