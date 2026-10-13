"""Mask well-known secret/token shapes in conversation text (opt-in, --redact).

High-precision patterns only, to avoid corrupting ordinary text: provider API
keys, cloud keys, VCS tokens, JWTs, private-key blocks, bearer tokens, and
``key = value`` style secrets. Each hit becomes ``[REDACTED:<kind>]``.

Redaction runs on the normalized conversation and (in a bundle) on the raw
bytes, so a redacted bundle is no longer byte-verbatim; that trade-off is the
point of the flag and is recorded as a warning.
"""

from __future__ import annotations

import re
from typing import Any, List, Tuple

_TOKEN = r"[A-Za-z0-9_\-]"

# (kind, compiled pattern, group index of the secret to mask; 0 = whole match)
_RULES: List[Tuple[str, "re.Pattern[str]", int]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), 0),
    ("anthropic-key", re.compile(r"sk-ant-" + _TOKEN + r"{20,}"), 0),
    ("openai-key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{20,}"), 0),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), 0),
    ("github-pat", re.compile(r"\bgithub_pat_" + _TOKEN + r"{20,}\b"), 0),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 0),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), 0),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"), 0),
    ("bearer", re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._\-]{20,})"), 1),
    ("assigned-secret", re.compile(
        r"(?i)\b(?:api[_\-]?key|secret|token|password|passwd|access[_\-]?key)\b\s*[:=]\s*[\"']?([A-Za-z0-9._\-]{12,})"), 1),
]


def redact_text(text: str) -> Tuple[str, int]:
    """Return (redacted text, number of secrets masked)."""
    if not isinstance(text, str) or not text:
        return text, 0
    total = 0
    for kind, pattern, group in _RULES:
        def repl(m: "re.Match[str]", _kind=kind, _g=group) -> str:
            if _g == 0:
                return f"[REDACTED:{_kind}]"
            return m.group(0).replace(m.group(_g), f"[REDACTED:{_kind}]", 1)

        text, n = pattern.subn(repl, text)
        total += n
    return text, total


def redact_obj(obj: Any) -> Tuple[Any, int]:
    """Recursively redact every string in a JSON-like structure. Returns (obj, count)."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, list):
        total = 0
        out = []
        for x in obj:
            red, n = redact_obj(x)
            out.append(red)
            total += n
        return out, total
    if isinstance(obj, dict):
        total = 0
        out = {}
        for k, v in obj.items():
            red, n = redact_obj(v)
            out[k] = red
            total += n
        return out, total
    return obj, 0
