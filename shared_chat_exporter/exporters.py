"""Export formats: jsonl, json, csv, md, txt, chat, html."""

from __future__ import annotations

import csv
import html as _html
import io
import json
import re
from typing import Any, Callable, Dict, List, Optional

from .extract import fence

Conv = Dict[str, Any]

EXT = {"jsonl": "jsonl", "json": "json", "csv": "csv", "md": "md", "txt": "txt", "chat": "jsonl", "html": "html"}
EXT_TO_FORMAT = {"jsonl": "jsonl", "ndjson": "jsonl", "json": "json", "csv": "csv", "md": "md",
                 "markdown": "md", "txt": "txt", "html": "html", "htm": "html"}
DESCRIPTIONS = {
    "jsonl": "one turn per line {share_id, title, turn, user_input, agent_output}",
    "json": "preservation structure (branches, raw message blocks, attachments, artifacts, capture, stats)",
    "csv": "spreadsheet table that opens directly in Excel (UTF-8 BOM)",
    "md": "readable document",
    "txt": "plain text that is easy to paste",
    "chat": "one conversation per line {messages:[{role,content}…]} (for fine-tuning)",
    "html": "self-contained HTML page with collapsible thinking and tool calls",
}


_ASSISTANT_LABEL = {"chatgpt": "ChatGPT", "codex": "Codex"}


def assistant_label(provider: Optional[str]) -> str:
    """Display name for the assistant side (Claude, ChatGPT, Codex, ...)."""
    return _ASSISTANT_LABEL.get(provider or "", "Claude")


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def rows(convs: List[Conv], only: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    for c in convs:
        for t in c["turns"]:
            row: Dict[str, Any] = {"share_id": c["source"]["share_id"], "title": c["source"]["title"], "turn": t["turn"]}
            if only != "assistant":
                row["user_input"] = t["user_input"]
            if only != "user":
                row["agent_output"] = t["agent_output"]
                for k in ("thinking", "tool_calls"):
                    if k in t:
                        row[k] = t[k]
            out.append(row)
    return out


def to_jsonl(convs: List[Conv], only: Optional[str] = None, **_: Any) -> str:
    return "".join(_dump(r) + "\n" for r in rows(convs, only))


def to_json(convs: List[Conv], **_: Any) -> str:
    keys = (
        "source", "options", "stats", "warnings", "preservation", "active_branch_id", "branches",
        "turns", "artifacts", "assets", "messages", "all_messages", "capture",
    )
    payload = [{k: c[k] for k in keys if k in c} for c in convs]
    return json.dumps(payload[0] if len(payload) == 1 else payload, ensure_ascii=False, indent=2) + "\n"


def to_csv(convs: List[Conv], only: Optional[str] = None, **_: Any) -> str:
    rs = rows(convs, only)
    cols = ["share_id", "title", "turn"]
    if only != "assistant":
        cols.append("user_input")
    if only != "user":
        cols.append("agent_output")
    cols += [k for k in ("thinking", "tool_calls") if any(k in r for r in rs)]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(cols)
    for r in rs:
        w.writerow(["" if r.get(c) is None else r[c] if isinstance(r.get(c), (str, int)) else _dump(r[c]) for c in cols])
    return "﻿" + buf.getvalue()


def _when(iso: Optional[str]) -> str:
    if not iso:
        return ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", iso)
    return f"{m.group(1)} {m.group(2)}" if m else iso


def to_markdown(convs: List[Conv], only: Optional[str] = None, **_: Any) -> str:
    md: List[str] = []
    for c in convs:
        src = c["source"]
        assistant = assistant_label(src.get("provider"))
        md.append("# " + (src["title"] or assistant + " conversation"))
        meta = [f"<{src['share_url']}>" if src.get("share_url") else "", _when(src.get("created_at")),
                f"{len(c['turns'])} turns"]
        md.append(" · ".join(x for x in meta if x))
        for t in c["turns"]:
            md.append(f"## Turn {t['turn']}")
            if only != "assistant":
                md.append("### User\n\n" + (t["user_input"] or "_(no input)_"))
            if only != "user":
                if t.get("thinking"):
                    md.append("<details><summary>Thinking</summary>\n\n" + t["thinking"] + "\n\n</details>")
                if t.get("tool_calls"):
                    j = json.dumps(t["tool_calls"], ensure_ascii=False, indent=2)
                    f = fence(j)
                    md.append(f"<details><summary>Tool calls ({len(t['tool_calls'])})</summary>\n\n{f}json\n{j}\n{f}\n\n</details>")
                md.append(f"### {assistant}\n\n" + (t["agent_output"] or "_(no text output)_"))
    return "\n\n".join(md) + "\n"


def to_text(convs: List[Conv], only: Optional[str] = None, **_: Any) -> str:
    out: List[str] = []
    for c in convs:
        src = c["source"]
        assistant = assistant_label(src.get("provider"))
        out.append(f"==== {src['title'] or assistant + ' conversation'} ====" + (f"\n{src['share_url']}" if src.get("share_url") else ""))
        for t in c["turns"]:
            if only != "assistant":
                out.append(f"[Turn {t['turn']}] User:\n{t['user_input']}")
            if only != "user":
                if t.get("thinking"):
                    out.append(f"[Turn {t['turn']}] Thinking:\n{t['thinking']}")
                if t.get("tool_calls"):
                    out.append(f"[Turn {t['turn']}] Tool calls:\n" + json.dumps(t["tool_calls"], ensure_ascii=False, indent=2))
                out.append(f"[Turn {t['turn']}] {assistant}:\n{t['agent_output']}")
    return "\n\n".join(out) + "\n"


def to_chat(convs: List[Conv], system: Optional[str] = None, **_: Any) -> str:
    lines = []
    for c in convs:
        msgs: List[Dict[str, str]] = [{"role": "system", "content": system}] if system else []
        for t in c["turns"]:
            if t["user_input"]:
                msgs.append({"role": "user", "content": t["user_input"]})
            if t["agent_output"]:
                msgs.append({"role": "assistant", "content": t["agent_output"]})
        lines.append(_dump({"messages": msgs, "metadata": {"share_id": c["source"]["share_id"], "title": c["source"]["title"]}}))
    return "\n".join(lines) + ("\n" if lines else "")


_HTML_CSS = """
:root{color-scheme:light dark}
body{font:16px/1.6 system-ui,sans-serif;max-width:820px;margin:0 auto;padding:24px 16px}
h1{font-size:1.5rem;margin:0 0 .2em}
.meta{color:#888;font-size:.85rem;margin-bottom:1.5em}
.turn{border-top:1px solid #8884;padding-top:1em;margin-top:1em}
.role{font-weight:700;margin:.6em 0 .2em}
.user .role{color:#b58900}.assistant .role{color:#268bd2}
.text{white-space:pre-wrap;overflow-wrap:anywhere}
details{margin:.5em 0;border:1px solid #8884;border-radius:6px;padding:.3em .6em}
summary{cursor:pointer;color:#888}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#8881;padding:.6em;border-radius:6px;margin:.4em 0}
.warn{color:#dc322f}
"""


def _esc(text: Any) -> str:
    return _html.escape("" if text is None else str(text))


def to_html(convs: List[Conv], only: Optional[str] = None, **_: Any) -> str:
    title0 = (convs[0]["source"].get("title") if convs else None) or "Conversation"
    out: List[str] = [
        "<!doctype html>", '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{_esc(title0)}</title><style>{_HTML_CSS}</style></head><body>",
    ]
    for c in convs:
        src = c["source"]
        assistant = assistant_label(src.get("provider"))
        out.append(f"<h1>{_esc(src.get('title') or assistant + ' conversation')}</h1>")
        meta = [src.get("share_url") or "", _when(src.get("created_at")), f"{len(c['turns'])} turns"]
        out.append(f'<div class="meta">{_esc(" · ".join(x for x in meta if x))}</div>')
        for w in c.get("warnings") or []:
            out.append(f'<div class="warn">! {_esc(w)}</div>')
        for t in c["turns"]:
            out.append(f'<div class="turn"><div class="turn-no">Turn {t["turn"]}</div>')
            if only != "assistant":
                out.append('<div class="user"><div class="role">User</div>'
                           f'<div class="text">{_esc(t["user_input"]) or "<em>(no input)</em>"}</div></div>')
            if only != "user":
                if t.get("thinking"):
                    out.append(f"<details><summary>Thinking</summary><pre>{_esc(t['thinking'])}</pre></details>")
                for call in t.get("tool_calls") or []:
                    body = json.dumps({k: call.get(k) for k in ("name", "input", "result", "is_error")},
                                      ensure_ascii=False, indent=2)
                    out.append(f"<details><summary>Tool: {_esc(call.get('name'))}</summary>"
                               f"<pre>{_esc(body)}</pre></details>")
                out.append(f'<div class="assistant"><div class="role">{_esc(assistant)}</div>'
                           f'<div class="text">{_esc(t["agent_output"]) or "<em>(no text output)</em>"}</div></div>')
            out.append("</div>")
    out.append("</body></html>")
    return "\n".join(out) + "\n"


FORMATS: Dict[str, Callable[..., str]] = {
    "jsonl": to_jsonl, "json": to_json, "csv": to_csv, "md": to_markdown, "txt": to_text,
    "chat": to_chat, "html": to_html,
}


def export(convs: List[Conv], fmt: str = "jsonl", *, only: Optional[str] = None, system: Optional[str] = None) -> str:
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format: {fmt} (available: {', '.join(FORMATS)})")
    return FORMATS[fmt](convs, only=only, system=system)
