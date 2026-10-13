"""Load local agent session logs into the common conversation model.

Supports two local, append-ordered JSONL logs:

- Claude Code transcripts (``~/.claude/projects/<proj>/<id>.jsonl``): ``user`` /
  ``assistant`` lines whose ``message`` holds the same content blocks
  (text/thinking/tool_use/tool_result) a Claude share snapshot uses.
- Codex rollouts (``~/.codex/sessions/**/rollout-*.jsonl``): the conversation is
  in ``response_item`` lines (message / reasoning / tool call + output).

Both are turned into a Claude-snapshot-shaped dict and handed to :func:`extract`,
which already does turn splitting, tool pairing and thinking. Logs are
append-ordered, not regeneration trees, so the transcript follows file order.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from .extract import ROOT_PARENT

CLAUDE_CODE = "claude-code"
CODEX = "codex"
_CONV_TYPES = ("user", "assistant")

# These log formats are undocumented and may change between releases. The
# adapters have only been tested against the current formats, observed locally on
# Claude Code log `version` 2.1.266–2.1.296 (latest 2.1.296) and Codex rollout
# `cli_version` 0.162.x. Detection stays lenient and unknown types are preserved.
TESTED_CLAUDE_CODE_VERSIONS = ("2.1.266", "2.1.296")
TESTED_CODEX_CLI_VERSION = "0.162.1"

# Codex injects context as developer/user messages wrapped in tags; these are
# harness scaffolding, not conversation turns, so they are left out of the transcript.
_CODEX_CONTEXT_PREFIXES = (
    "<environment_context", "<user_instructions", "<skills", "<persistent", "<system",
)


def _ver_tuple(s: Any) -> tuple:
    out = []
    for part in str(s or "").split("."):
        if part.isdigit():
            out.append(int(part))
        else:
            break
    return tuple(out)


def _drift_warning(kind: str, version: Any, lo: str, hi: Optional[str] = None) -> Optional[str]:
    """Warn when a log's version is outside the range the adapter was tested on.

    The formats are undocumented, so a version drift is the most likely cause of
    silent mis-parsing; this surfaces it instead of failing quietly.
    """
    v = _ver_tuple(version)
    if not v:
        return None
    if hi is None:  # single tested version: compare on major.minor
        if v[:2] != _ver_tuple(lo)[:2]:
            return f"{kind} log version {version} is outside the tested {lo} series; parsing may be imperfect."
        return None
    if not (_ver_tuple(lo) <= v <= _ver_tuple(hi)):
        return f"{kind} log version {version} is outside the tested range {lo}–{hi}; parsing may be imperfect."
    return None


def _normalize_newlines(obj: Any) -> Any:
    """Convert CRLF and lone CR to LF in every string, recursively.

    The raw log keeps its original bytes in the bundle; this only affects the
    normalized conversation/transcript so line breaks render as plain newlines.
    """
    if isinstance(obj, str):
        return obj.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(obj, list):
        return [_normalize_newlines(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _normalize_newlines(v) for k, v in obj.items()}
    return obj


def _iter_jsonl(path: Union[str, Path]) -> Iterator[Dict[str, Any]]:
    # Text mode uses universal newlines, so a trailing \r from CRLF files is dropped.
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def detect_session(path: Union[str, Path]) -> Optional[str]:
    """Return "claude-code", "codex", or None for the log at ``path``.

    A Claude share snapshot or ChatGPT capture is a single JSON object, so its
    first line never parses as a per-line event and this returns None (the caller
    then falls back to the snapshot parser).
    """
    for seen, obj in enumerate(_iter_jsonl(path)):
        if seen >= 50:
            break
        t = obj.get("type")
        if t in _CONV_TYPES and isinstance(obj.get("message"), dict):
            return CLAUDE_CODE
        if isinstance(obj.get("sessionId"), str) and isinstance(t, str):
            return CLAUDE_CODE
        if t in ("session_meta", "response_item", "turn_context", "event_msg") and isinstance(obj.get("payload"), dict):
            return CODEX
    return None


def _chain(messages: List[Dict[str, Any]]) -> None:
    """Link messages linearly in file order and number them (snapshot shape)."""
    for i, m in enumerate(messages):
        m.setdefault("uuid", f"m-{i}")
        m["parent_message_uuid"] = messages[i - 1]["uuid"] if i else ROOT_PARENT
        m["index"] = i


def _build_snapshot(messages: List[Dict[str, Any]], meta: Dict[str, Any]) -> Dict[str, Any]:
    _chain(messages)
    snap: Dict[str, Any] = {
        "uuid": meta.get("uuid") or "session",
        "name": meta.get("title") or "",
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "chat_messages": messages,
    }
    for k in ("model", "_provider", "_warnings", "_uncertain"):
        if meta.get(k):
            snap[k] = meta[k]
    return snap


# ------------------------------------------------------------------ Claude Code
def _claude_code_snapshot(path: Path) -> Dict[str, Any]:
    messages: List[Dict[str, Any]] = []
    session_id = title = model = log_version = None
    first_ts = last_ts = None
    skipped_sidechain = 0
    for obj in _iter_jsonl(path):
        session_id = session_id or obj.get("sessionId")
        log_version = log_version or obj.get("version")
        if obj.get("type") == "ai-title" and isinstance(obj.get("aiTitle"), str):
            title = obj["aiTitle"]
        if obj.get("type") not in _CONV_TYPES:
            continue
        if obj.get("isSidechain"):  # sub-agent side thread; kept in raw bundle, not the transcript
            skipped_sidechain += 1
            continue
        message = obj.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        ts = obj.get("timestamp")
        first_ts = first_ts or ts
        last_ts = ts or last_ts
        model = model or message.get("model")
        snap_msg: Dict[str, Any] = _normalize_newlines(dict(message))
        snap_msg["uuid"] = obj.get("uuid") or f"cc-{len(messages)}"
        snap_msg["_cc_parent_uuid"] = obj.get("parentUuid")  # original link kept, transcript is linear
        snap_msg["sender"] = "human" if role == "user" else "assistant" if role == "assistant" else str(role)
        snap_msg["created_at"] = ts
        content = message.get("content")
        if isinstance(content, str):
            snap_msg["text"] = content
            snap_msg.pop("content", None)
        messages.append(snap_msg)
    warnings = []
    if skipped_sidechain:
        warnings.append(
            f"{skipped_sidechain} sub-agent (sidechain) messages are kept in the raw log "
            "but excluded from the main transcript."
        )
    drift = _drift_warning("Claude Code", log_version, *TESTED_CLAUDE_CODE_VERSIONS)
    if drift:
        warnings.append(drift)
    return _build_snapshot(messages, {
        "uuid": session_id or path.stem, "title": title, "model": model,
        "created_at": first_ts, "updated_at": last_ts,
        "_provider": CLAUDE_CODE, "_warnings": warnings,
    })


# ------------------------------------------------------------------ Codex
def _codex_text(val: Any) -> str:
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return "\n".join(b.get("text", "") for b in val if isinstance(b, dict) and isinstance(b.get("text"), str))
    return "" if val is None else str(val)


def _codex_snapshot(path: Path) -> Dict[str, Any]:
    messages: List[Dict[str, Any]] = []
    session_id = title = model = cli_version = None
    first_ts = last_ts = None
    skipped_context = encrypted_reasoning = 0

    def add(sender: str, block: Dict[str, Any], ts: Optional[str]) -> None:
        messages.append({"sender": sender, "created_at": ts, "content": [block]})

    for obj in _iter_jsonl(path):
        t = obj.get("type")
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
        ts = obj.get("timestamp")
        if t == "session_meta":
            session_id = payload.get("session_id") or payload.get("id") or session_id
            cli_version = cli_version or payload.get("cli_version")
            first_ts = first_ts or payload.get("timestamp") or ts
            continue
        if t == "turn_context":
            model = model or payload.get("model")
            continue
        if t != "response_item":
            continue
        last_ts = ts or last_ts
        first_ts = first_ts or ts
        pt = payload.get("type")
        if pt == "message":
            role = payload.get("role")
            text = _normalize_newlines(_codex_text(payload.get("content")))
            if role == "developer" or not text.strip():
                continue
            if role == "user" and text.lstrip().startswith(_CODEX_CONTEXT_PREFIXES):
                skipped_context += 1
                continue
            sender = "human" if role == "user" else "assistant"
            if sender == "human" and title is None:
                title = text.strip().splitlines()[0][:60]
            add(sender, {"type": "text", "text": text}, ts)
        elif pt == "reasoning":
            if payload.get("encrypted_content"):
                encrypted_reasoning += 1
            summary = _normalize_newlines(_codex_text([
                s for s in (payload.get("summary") or []) if isinstance(s, dict)
            ]))
            if summary.strip():
                add("assistant", {"type": "thinking", "thinking": summary}, ts)
        elif pt in ("custom_tool_call", "function_call"):
            raw_input = payload.get("input")
            if raw_input is None and isinstance(payload.get("arguments"), str):
                try:
                    raw_input = json.loads(payload["arguments"])
                except json.JSONDecodeError:
                    raw_input = {"arguments": payload["arguments"]}
            if not isinstance(raw_input, dict):
                raw_input = {"input": raw_input}
            add("assistant", {"type": "tool_use", "id": payload.get("call_id"),
                              "name": payload.get("name") or "", "input": _normalize_newlines(raw_input)}, ts)
        elif pt in ("custom_tool_call_output", "function_call_output"):
            add("human", {"type": "tool_result", "tool_use_id": payload.get("call_id"),
                          "content": _normalize_newlines(_codex_text(payload.get("output"))),
                          "is_error": False}, ts)

    uncertain = []
    if encrypted_reasoning:
        uncertain.append({
            "item": "reasoning",
            "reason": f"{encrypted_reasoning} Codex reasoning blocks are encrypted (encrypted_content); "
                      "only the plain-text summary is preserved.",
        })
    warnings = []
    if skipped_context:
        warnings.append(f"{skipped_context} Codex context/instruction messages excluded from the transcript "
                        "(kept in the raw log).")
    drift = _drift_warning("Codex", cli_version, TESTED_CODEX_CLI_VERSION)
    if drift:
        warnings.append(drift)
    return _build_snapshot(messages, {
        "uuid": session_id or path.stem.replace("rollout-", ""), "title": title, "model": model,
        "created_at": first_ts, "updated_at": last_ts,
        "_provider": CODEX, "_warnings": warnings, "_uncertain": uncertain,
    })


_BUILDERS = {CLAUDE_CODE: _claude_code_snapshot, CODEX: _codex_snapshot}


def session_to_snapshot(path: Union[str, Path], provider: Optional[str] = None) -> Dict[str, Any]:
    """Transform a session log into a Claude-snapshot-shaped dict.

    Message content has CRLF/CR normalized to LF; the raw log keeps original bytes.
    """
    path = Path(path)
    provider = provider or detect_session(path)
    builder = _BUILDERS.get(provider)
    if builder is None:
        raise ValueError(f"not a recognized session log: {path}")
    return builder(path)


def finalize_session(conv: Dict[str, Any], path: Union[str, Path], snap: Dict[str, Any]) -> Dict[str, Any]:
    """Fix provider-specific fields on a conversation extracted from a session snapshot."""
    provider = snap.get("_provider", CLAUDE_CODE)
    src = conv["source"]
    src["provider"] = provider
    src["share_url"] = None
    src["session_file"] = str(path)
    if not src.get("title"):
        src["title"] = Path(path).stem
    conv["provider"] = provider
    for w in snap.get("_warnings") or []:
        conv.setdefault("warnings", []).append(w)
    unc = snap.get("_uncertain") or []
    if unc:
        conv.setdefault("preservation", {}).setdefault("uncertain", []).extend(unc)
    return conv
