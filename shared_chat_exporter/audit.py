"""Bundle integrity audit report and verification (provider-neutral).

The audit report records the **byte-level** SHA-256 and size of every stored
file. ``verify`` recomputes the SHA-256 from the actual files on disk, compares
them with the report, and also checks the report's own schema.
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
    "This report proves the stored file bytes have not changed since export. "
    "It does not prove the share page exposed every token of the original conversation.",
    "Snapshot and share-page formats are not public, stable export APIs and may change without notice.",
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
    """``files`` = {relative path: bytes}. Records each file's size and byte-level SHA-256."""
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
    """Check the audit report's structure and return a list of problems (empty = valid)."""
    errs: List[str] = []
    if not isinstance(audit, dict):
        return ["audit is not a JSON object"]
    for key, typ in _REQUIRED:
        if key not in audit:
            errs.append(f"missing required key: {key}")
        elif not isinstance(audit[key], typ):
            errs.append(f"{key} wrong type: {type(audit[key]).__name__}")
    if "schemaVersion" in audit and audit["schemaVersion"] != SCHEMA_VERSION:
        errs.append(f"schemaVersion mismatch: {audit.get('schemaVersion')} (supported {SCHEMA_VERSION})")
    files = audit.get("files")
    if isinstance(files, list):
        seen = set()
        for i, e in enumerate(files):
            if not isinstance(e, dict):
                errs.append(f"files[{i}] is not an object")
                continue
            for k, typ in (("path", str), ("sha256", str), ("bytes", int)):
                if k not in e:
                    errs.append(f"files[{i}].{k} missing")
                elif not isinstance(e[k], typ):
                    errs.append(f"files[{i}].{k} wrong type")
            path = e.get("path")
            if isinstance(path, str):
                if path in seen:
                    errs.append(f"duplicate path: {path}")
                seen.add(path)
            if isinstance(e.get("sha256"), str) and len(e["sha256"]) != 64:
                errs.append(f"files[{i}].sha256 wrong length")
    return errs


def verify(audit: Union[Dict[str, Any], str, Path], base_dir: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Re-verify each file of an audit report (dict or audit.json path) byte-for-byte under ``base_dir``.

    Returns: {ok, checked, mismatches, missing, schema_errors}.
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
