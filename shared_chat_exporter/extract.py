"""Split a snapshot into user-input / agent-output turns.

One turn = a single user message plus every agent response up to the next user
message. A human message that holds only tool results (API-style conversation)
does not start a new turn.
"""

from __future__ import annotations

import posixpath
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

ROOT_PARENT = "00000000-0000-4000-8000-000000000000"

ARTIFACT_EXT = {
    "text/markdown": "md",
    "text/html": "html",
    "image/svg+xml": "svg",
    "application/vnd.ant.react": "jsx",
    "application/vnd.ant.mermaid": "mmd",
}
ARTIFACT_LANG = {"md": "markdown", "html": "html", "svg": "svg", "jsx": "jsx", "mmd": "mermaid"}
LANG_EXT = {
    "python": "py", "javascript": "js", "typescript": "ts", "tsx": "tsx", "jsx": "jsx", "java": "java",
    "c": "c", "cpp": "cpp", "c++": "cpp", "csharp": "cs", "go": "go", "rust": "rs", "ruby": "rb",
    "php": "php", "swift": "swift", "kotlin": "kt", "bash": "sh", "shell": "sh", "sh": "sh",
    "powershell": "ps1", "sql": "sql", "json": "json", "yaml": "yaml", "toml": "toml", "css": "css",
    "html": "html", "markdown": "md", "r": "r", "dart": "dart", "scala": "scala", "lua": "lua",
}
EXT_LANG = {v: k for k, v in reversed(list(LANG_EXT.items()))}
FILE_CREATE_TOOLS = {"create_file", "write_file", "write"}
FILE_EDIT_TOOLS = {"str_replace", "str_replace_editor", "str_replace_based_edit_tool", "edit_file", "edit"}


@dataclass
class Options:
    attachments: bool = True   # include attachment/pasted text in user input
    artifacts: bool = True     # include artifact/generated-file content in agent output
    tools: bool = False        # include tool calls and results as tool_calls
    thinking: bool = False     # include the thinking process as thinking


def fence(text: str) -> str:
    """Pick a fence longer than any backtick run inside the content."""
    longest = 0
    run = 0
    for ch in str(text):
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


def _flatten(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    out = []
    for c in content:
        if not isinstance(c, dict):
            continue
        if isinstance(c.get("text"), str):
            out.append(f"{c['title']}\n{c['text']}" if c.get("title") else c["text"])
        elif isinstance(c.get("content"), list):
            out.append(_flatten(c["content"]))
    return "\n\n".join(x for x in out if x)


def _main_path(snap: Dict[str, Any], warnings: List[str]) -> List[Dict[str, Any]]:
    """Pick the active branch to use for the human-readable transcript."""
    msgs = [m for m in snap.get("chat_messages") or [] if isinstance(m, dict)]
    if msgs and all(isinstance(m.get("index"), int) for m in msgs):
        msgs.sort(key=lambda m: m["index"])
    if len(msgs) < 2 or not all(m.get("uuid") and m.get("parent_message_uuid") for m in msgs):
        return msgs
    if all(i == 0 or m["parent_message_uuid"] == msgs[i - 1]["uuid"] for i, m in enumerate(msgs)):
        return msgs
    by_id = {m["uuid"]: m for m in msgs}
    leaf = by_id.get(snap.get("current_leaf_message_uuid")) or msgs[-1]
    path, cur, seen = [], leaf, set()
    while cur is not None and cur["uuid"] not in seen:
        seen.add(cur["uuid"])
        path.append(cur)
        parent = cur.get("parent_message_uuid")
        cur = None if parent == ROOT_PARENT else by_id.get(parent)
    path.reverse()
    if len(path) < len(msgs):
        warnings.append(
            f"The conversation has branches (regenerations/edits). The transcript shows the "
            f"active branch of {len(path)} messages; all {len(msgs)} messages are preserved in branches."
        )
    return path


def _meta(b: Dict[str, Any], *drop: str) -> Dict[str, Any]:
    """Preserve a block's raw fields except those normalization already extracted."""
    skip = {"type", *drop}
    return {k: v for k, v in b.items() if k not in skip}


def _norm_message(m: Dict[str, Any]) -> Dict[str, Any]:
    sender = m.get("sender")
    role = "user" if sender == "human" else "assistant" if sender == "assistant" else str(sender or "unknown")
    raw = m.get("content") if isinstance(m.get("content"), list) and m.get("content") else (
        [{"type": "text", "text": m["text"]}] if isinstance(m.get("text"), str) and m.get("text") else []
    )
    blocks: List[Dict[str, Any]] = []
    for b in raw:
        if not isinstance(b, dict):
            blocks.append({"type": "unknown", "subtype": None, "raw": b})
            continue
        t = b.get("type")
        if t == "text" and isinstance(b.get("text"), str):
            block = {"type": "text", "text": b["text"]}
            if b.get("citations"):
                block["citations"] = b["citations"]
            meta = _meta(b, "text")
            if meta:
                block["meta"] = meta
            blocks.append(block)
        elif t in ("thinking", "redacted_thinking"):
            th = b.get("thinking") if isinstance(b.get("thinking"), str) else b.get("text")
            if isinstance(th, str) and th:
                block = {"type": "thinking", "text": th, "subtype": t}
                meta = _meta(b, "thinking", "text")
                if meta:
                    block["meta"] = meta
                blocks.append(block)
            else:
                blocks.append({"type": "unknown", "subtype": t, "raw": b})
        elif t in ("tool_use", "server_tool_use"):
            block = {"type": "tool_use", "id": b.get("id"), "name": b.get("name") or "",
                     "input": b.get("input") if isinstance(b.get("input"), dict) else {}, "subtype": t}
            meta = _meta(b, "id", "name", "input")
            if meta:
                block["meta"] = meta
            blocks.append(block)
        elif t == "tool_result" or (isinstance(t, str) and t.endswith("_tool_result")):
            block = {"type": "tool_result", "tool_use_id": b.get("tool_use_id"), "name": b.get("name") or "",
                     "is_error": bool(b.get("is_error")), "text": _flatten(b.get("content")), "subtype": t}
            if b.get("content") is not None:
                block["content_raw"] = b["content"]
            meta = _meta(b, "tool_use_id", "name", "is_error", "content")
            if meta:
                block["meta"] = meta
            blocks.append(block)
        elif isinstance(b.get("text"), str) and b["text"]:
            lang = b.get("language")
            block = {"type": "text", "text": f"```{lang}\n{b['text']}\n```" if lang else b["text"],
                     "subtype": t}
            if b.get("citations"):
                block["citations"] = b["citations"]
            meta = _meta(b, "text")
            if meta:
                block["meta"] = meta
            blocks.append(block)
        else:
            blocks.append({"type": "unknown", "subtype": t, "raw": b})
    attachments = []
    for a in m.get("attachments") or []:
        if isinstance(a, dict):
            content = a.get("extracted_content")
            entry = {"name": a.get("file_name") or "attachment", "content": content if isinstance(content, str) else ""}
            meta = {k: v for k, v in a.items() if k not in ("file_name", "extracted_content")}
            if meta:
                entry["meta"] = meta
            attachments.append(entry)
        else:
            attachments.append({"name": "attachment", "content": "", "meta": {"raw": a}})
    files: List[str] = []
    files_meta: List[Dict[str, Any]] = []
    for f in list(m.get("files") or []) + list(m.get("files_v2") or []):
        if isinstance(f, dict):
            name = f.get("file_name") or f.get("file_uuid") or "file"
            files_meta.append({"name": name, "meta": {k: v for k, v in f.items() if k != "file_name"}})
        else:
            name = "file"
            files_meta.append({"name": name, "meta": {"raw": f}})
        if name not in files:
            files.append(name)
    extracted = {"index", "uuid", "parent_message_uuid", "sender", "content", "text",
                 "created_at", "stop_reason", "attachments", "files", "files_v2"}
    msg_meta = {k: v for k, v in m.items() if k not in extracted}
    out = {
        "index": m.get("index") if isinstance(m.get("index"), int) else None,
        "uuid": m.get("uuid"),
        "parent_uuid": m.get("parent_message_uuid"),
        "sender": sender,
        "role": role,
        "created_at": m.get("created_at"),
        "stop_reason": m.get("stop_reason"),
        "text": "\n\n".join(b["text"] for b in blocks if b["type"] == "text" and isinstance(b.get("text"), str)).strip(),
        "blocks": blocks,
        "attachments": attachments,
        "files": files,
        "files_meta": files_meta,
    }
    if msg_meta:
        out["meta"] = msg_meta
    return out


class _Artifacts:
    """Track every version of artifacts/files created and edited during a conversation."""

    def __init__(self) -> None:
        self.items: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []  # all change events (including failed applications)

    def apply(self, name: str, inp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Apply one tool call; for an artifact change, return (action, artifact)."""
        if name == "artifacts":
            key = str(inp.get("id") or inp.get("title") or "artifact")
            cmd = inp.get("command") or ("create" if isinstance(inp.get("content"), str) else "")
            if cmd in ("create", "rewrite") and isinstance(inp.get("content"), str):
                return self._set(key, inp["content"], cmd, title=inp.get("title"), type_=inp.get("type"),
                                 language=inp.get("language"))
            if cmd == "update" and isinstance(inp.get("new_str"), str):
                return self._edit(key, inp.get("old_str"), inp["new_str"])
            return None
        path = inp.get("path") or inp.get("file_path")
        if isinstance(inp.get("file_text"), str) and (name in FILE_CREATE_TOOLS or path):
            return self._set(str(path or name), inp["file_text"], "create", title=path)
        if name in FILE_EDIT_TOOLS and path and isinstance(inp.get("new_str"), str):
            if inp.get("command") in (None, "str_replace"):
                return self._edit(str(path), inp.get("old_str"), inp["new_str"])
        return None

    def _set(self, key, content, action, title=None, type_=None, language=None):
        prev = self.items.get(key, {})
        ext = ARTIFACT_EXT.get(type_ or "") or LANG_EXT.get(str(language or "").lower())
        if not ext and title and "." in posixpath.basename(str(title)):
            ext = posixpath.basename(str(title)).rsplit(".", 1)[1].lower()
        resolved_action = "rewrite" if prev and action == "create" else action
        version = prev.get("versions", 0) + 1
        art = {
            "key": key,
            "title": str(title or prev.get("title") or key),
            "type": type_ or prev.get("type") or "",
            "language": language or prev.get("language") or ARTIFACT_LANG.get(ext or "") or EXT_LANG.get(ext or "", ""),
            "ext": ext or prev.get("ext") or "txt",
            "content": content,
            "versions": version,
            "history": list(prev.get("history", [])),
        }
        art["history"].append({"version": version, "action": resolved_action, "content": content,
                               "title": art["title"], "ext": art["ext"], "language": art["language"]})
        self.items[key] = art
        self.events.append({"key": key, "action": resolved_action, "version": version, "applied": True})
        return {"action": resolved_action, "artifact": art}

    def _edit(self, key, old, new):
        prev = self.items.get(key)
        if prev is None:
            self.events.append({"key": key, "action": "update", "version": None, "applied": False,
                                "reason": "update before create (no artifact)"})
            return {"action": "update", "artifact": None, "key": key, "unapplied": True}
        content = prev["content"]
        if isinstance(old, str) and old and old in content:
            content = content.replace(old, new, 1)
        else:
            self.events.append({"key": key, "action": "update", "version": None, "applied": False,
                                "reason": "old_str not found in current content"})
            return {"action": "update", "artifact": None, "key": key, "unapplied": True}
        res = self._set(key, content, "update")
        res["action"] = "update"
        return res


def _build_branches(snap: Dict[str, Any], active: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Preserve every branch exposed in the snapshot (does not mutate the original dict).

    The active path stays in turns/messages; here the whole tree is recorded as
    nodes and root->leaf paths. Each node keeps uuid, parent and whether it is active.
    """
    all_msgs = [m for m in snap.get("chat_messages") or [] if isinstance(m, dict)]
    active_ids = [m.get("uuid") for m in active]
    active_set = {i for i in active_ids if i}
    active_leaf = active_ids[-1] if active_ids else None
    linked = len(all_msgs) >= 2 and all(m.get("uuid") and m.get("parent_message_uuid") for m in all_msgs)

    nodes: List[Dict[str, Any]] = []
    for m in all_msgs:
        norm = _norm_message(m)
        uid = norm["uuid"]
        nodes.append({
            "uuid": uid,
            "parent_uuid": norm["parent_uuid"],
            "index": norm["index"],
            "role": norm["role"],
            "created_at": norm["created_at"],
            "is_active": bool(uid) and uid in active_set,
            "message": norm,
        })

    paths: List[Dict[str, Any]] = []
    if linked:
        by_id = {m["uuid"]: m for m in all_msgs}
        parents = {m.get("parent_message_uuid") for m in all_msgs}
        leaves = [m["uuid"] for m in all_msgs if m["uuid"] not in parents]
        for leaf in leaves:
            chain: List[str] = []
            cur: Optional[str] = leaf
            seen: set = set()
            while cur is not None and cur in by_id and cur not in seen:
                seen.add(cur)
                chain.append(cur)
                parent = by_id[cur].get("parent_message_uuid")
                cur = None if parent == ROOT_PARENT else parent
            chain.reverse()
            paths.append({"leaf_uuid": leaf, "is_active": leaf == active_leaf,
                          "length": len(chain), "message_uuids": chain})
    else:
        paths.append({"leaf_uuid": active_leaf, "is_active": True,
                      "length": len(active_ids), "message_uuids": list(active_ids)})

    return {"active_leaf_uuid": active_leaf, "linked": linked, "nodes": nodes, "paths": paths}


def extract(snap: Dict[str, Any], options: Optional[Options] = None, **kw: Any) -> Dict[str, Any]:
    """Snapshot dict -> conversation dict (source, turns, messages, branches, artifacts, stats, warnings)."""
    opts = options or Options(**kw)
    warnings: List[str] = []
    active = _main_path(snap, warnings)
    messages = [_norm_message(m) for m in active]
    branches = _build_branches(snap, active)
    arts = _Artifacts()
    turns: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    unapplied = 0

    def new_turn(at):
        t = {"turn": len(turns) + 1, "user_input": "", "agent_output": "", "user_at": at, "agent_at": None,
             "attachments": [], "_out": [], "_think": [], "_tools": []}
        turns.append(t)
        return t

    for msg in messages:
        tool_only = (msg["role"] == "user" and not msg["text"] and msg["blocks"]
                     and all(b["type"] == "tool_result" for b in msg["blocks"]))
        if msg["role"] == "user" and not tool_only:
            cur = new_turn(msg["created_at"])
            parts = [msg["text"]] if msg["text"] else []
            if opts.attachments:
                for a in msg["attachments"]:
                    parts.append(f"[attachment: {a['name']}]" + (f"\n{a['content']}" if a["content"] else ""))
                parts += [f"[file: {f}]" for f in msg["files"]]
            cur["user_input"] = "\n\n".join(parts).strip()
            cur["attachments"] = [a["name"] for a in msg["attachments"]] + msg["files"]
            continue
        if cur is None:
            cur = new_turn(None)
        cur["agent_at"] = msg["created_at"] or cur["agent_at"]
        for b in msg["blocks"]:
            if b["type"] == "text":
                cur["_out"].append(b["text"])
            elif b["type"] == "thinking":
                cur["_think"].append(b["text"])
            elif b["type"] == "tool_use":
                change = arts.apply(b["name"], b["input"])
                if change and change.get("unapplied"):
                    unapplied += 1
                if change and change.get("artifact") and opts.artifacts:
                    a = change["artifact"]
                    label = {"create": "Artifact", "rewrite": "Artifact rewrite", "update": "Artifact update"}[change["action"]]
                    body = a["content"].rstrip("\n")
                    f = fence(body)
                    cur["_out"].append(f"[{label}: {a['title']}]\n{f}{a['language']}\n{body}\n{f}")
                cur["_tools"].append({"id": b["id"], "name": b["name"], "input": b["input"], "result": None,
                                      "is_error": False})
            elif b["type"] == "tool_result":
                hit = None
                for c in reversed(cur["_tools"]):
                    if (b["tool_use_id"] and c["id"] == b["tool_use_id"]) or (not b["tool_use_id"] and c["result"] is None):
                        hit = c
                        break
                if hit is None:
                    hit = {"id": b["tool_use_id"], "name": b["name"], "input": None, "result": None, "is_error": False}
                    cur["_tools"].append(hit)
                hit["result"], hit["is_error"] = b["text"], b["is_error"]

    if unapplied:
        warnings.append(f"{unapplied} artifact update(s) could not be applied because the original content was not found.")

    tool_counter: Counter = Counter()
    for t in turns:
        t["agent_output"] = "\n\n".join(t["_out"]).strip()
        if opts.thinking:
            t["thinking"] = "\n\n".join(t["_think"]).strip()
        if opts.tools:
            t["tool_calls"] = [{k: c[k] for k in ("name", "input", "result", "is_error")} for c in t["_tools"]]
        t["tool_call_count"] = len(t["_tools"])
        tool_counter.update(c["name"] or "?" for c in t["_tools"])
        for k in ("_out", "_think", "_tools"):
            del t[k]

    sid = snap.get("uuid")
    from .snapshot import share_page_url  # avoid circular import

    source = {
        "share_id": sid,
        "share_url": share_page_url(sid) if sid else None,
        "title": snap.get("snapshot_name") or snap.get("name") or "",
        "created_at": snap.get("created_at"),
        "updated_at": snap.get("updated_at"),
    }
    if snap.get("model"):
        source["model"] = snap.get("model")
    source["provider"] = "claude"
    total_msgs = len([m for m in snap.get("chat_messages") or [] if isinstance(m, dict)])
    stats = {
        "turns": len(turns),
        "messages": len(messages),
        "messages_in_snapshot": total_msgs,
        "user_chars": sum(len(t["user_input"]) for t in turns),
        "assistant_chars": sum(len(t["agent_output"]) for t in turns),
        "tool_calls": dict(tool_counter.most_common()),
        "attachments": sum(len(m["attachments"]) + len(m["files"]) for m in messages if m["role"] == "user"),
        "artifacts": len(arts.items),
        "thinking_blocks": sum(1 for m in messages for b in m["blocks"] if b["type"] == "thinking"),
        "branches": len(branches["paths"]),
        "alternate_branches": sum(1 for p in branches["paths"] if not p["is_active"]),
    }
    uncertain = [
        {"item": "hidden-or-server-only-data",
         "reason": "private data and hidden reasoning the server did not include in the share snapshot cannot be recovered"},
    ]
    for node in branches["nodes"]:
        message = node.get("message") or {}
        for file_meta in message.get("files_meta") or []:
            uncertain.append({"item": f"file:{file_meta.get('name') or 'unknown'}",
                              "reason": "the share snapshot has only file metadata, not the binary original"})
    return {
        "provider": "claude",
        "source": source,
        "options": asdict(opts),
        "turns": turns,
        "messages": messages,
        "all_messages": [node["message"] for node in branches["nodes"]],
        "branches": branches,
        "artifacts": list(arts.items.values()),
        "artifact_events": arts.events,
        "stats": stats,
        "warnings": warnings,
        "preservation": {
            "captured": ["raw snapshot", "all exposed message branches", "raw/unknown blocks",
                         "citations", "tool calls/results", "artifact version history", "attachment metadata"],
            "dropped": [],
            "uncertain": uncertain,
            "limitations": [
                "Hidden reasoning or private data the server did not send to the share snapshot cannot be retrieved.",
                "When a binary attachment's original is absent from the snapshot, only its metadata and the failure reason are preserved.",
            ],
        },
    }
