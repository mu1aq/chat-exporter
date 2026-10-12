"""스냅샷을 사용자 입력 ↔ 에이전트 출력 턴으로 나눕니다.

턴 하나 = 사용자 메시지 1개 + 다음 사용자 메시지 전까지의 모든 에이전트 응답.
도구 결과만 담긴 human 메시지(API 형식 대화)는 새 턴으로 치지 않습니다.
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
    attachments: bool = True   # 첨부·붙여넣은 텍스트를 사용자 입력에 포함
    artifacts: bool = True     # 아티팩트·생성 파일 내용을 에이전트 출력에 포함
    tools: bool = False        # 도구 호출과 결과를 tool_calls 로 포함
    thinking: bool = False     # 생각 과정을 thinking 으로 포함


def fence(text: str) -> str:
    """내용 안의 ``` 보다 긴 펜스를 고릅니다."""
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
    """사람이 읽는 transcript에 사용할 활성 갈래를 고릅니다."""
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
            f"대화에 분기(다시 생성·수정)가 있습니다. transcript는 활성 갈래 "
            f"{len(path)}개 메시지를 표시하고, 전체 {len(msgs)}개 메시지는 branches에 보존했습니다."
        )
    return path


def _meta(b: Dict[str, Any], *drop: str) -> Dict[str, Any]:
    """블록의 원본 필드 중 정규화로 이미 뽑아낸 것 말고 남는 것을 보존합니다."""
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
            entry = {"name": a.get("file_name") or "첨부", "content": content if isinstance(content, str) else ""}
            meta = {k: v for k, v in a.items() if k not in ("file_name", "extracted_content")}
            if meta:
                entry["meta"] = meta
            attachments.append(entry)
        else:
            attachments.append({"name": "첨부", "content": "", "meta": {"raw": a}})
    files: List[str] = []
    files_meta: List[Dict[str, Any]] = []
    for f in list(m.get("files") or []) + list(m.get("files_v2") or []):
        if isinstance(f, dict):
            name = f.get("file_name") or f.get("file_uuid") or "파일"
            files_meta.append({"name": name, "meta": {k: v for k, v in f.items() if k != "file_name"}})
        else:
            name = "파일"
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
    """대화 중에 만들어지고 고쳐지는 아티팩트·파일의 모든 버전을 따라갑니다."""

    def __init__(self) -> None:
        self.items: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []  # 모든 변경 이벤트 (적용 실패 포함)

    def apply(self, name: str, inp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """도구 호출 하나를 반영하고, 아티팩트 변경이면 (동작, 아티팩트)를 돌려줍니다."""
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
                                "reason": "update before create (아티팩트 없음)"})
            return {"action": "update", "artifact": None, "key": key, "unapplied": True}
        content = prev["content"]
        if isinstance(old, str) and old and old in content:
            content = content.replace(old, new, 1)
        else:
            self.events.append({"key": key, "action": "update", "version": None, "applied": False,
                                "reason": "old_str를 현재 내용에서 찾지 못함"})
            return {"action": "update", "artifact": None, "key": key, "unapplied": True}
        res = self._set(key, content, "update")
        res["action"] = "update"
        return res


def _build_branches(snap: Dict[str, Any], active: List[Dict[str, Any]]) -> Dict[str, Any]:
    """스냅샷에 노출된 모든 분기를 보존합니다 (원본 dict를 바꾸지 않음).

    active 경로는 turns/messages 에 그대로 두고, 여기서는 전체 트리를 노드와
    루트→leaf 경로로 기록합니다. 각 노드에 uuid·parent·active 여부를 남깁니다.
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
    """스냅샷 dict → 대화 dict (source, turns, messages, branches, artifacts, stats, warnings)."""
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
                    parts.append(f"[첨부: {a['name']}]" + (f"\n{a['content']}" if a["content"] else ""))
                parts += [f"[파일: {f}]" for f in msg["files"]]
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
                    label = {"create": "아티팩트", "rewrite": "아티팩트 다시 작성", "update": "아티팩트 수정"}[change["action"]]
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
        warnings.append(f"아티팩트 수정 {unapplied}건은 원래 내용을 찾지 못해 반영하지 못했습니다.")

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
    from .snapshot import share_page_url  # 순환 import 방지

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
         "reason": "공유 스냅샷에 서버가 포함하지 않은 비공개 데이터와 숨은 reasoning은 복구할 수 없음"},
    ]
    for node in branches["nodes"]:
        message = node.get("message") or {}
        for file_meta in message.get("files_meta") or []:
            uncertain.append({"item": f"file:{file_meta.get('name') or 'unknown'}",
                              "reason": "공유 스냅샷에는 파일 메타데이터만 있고 바이너리 원본이 없음"})
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
                "숨은 reasoning이나 서버가 공유 스냅샷으로 보내지 않은 비공개 데이터는 가져올 수 없습니다.",
                "바이너리 첨부 원본이 스냅샷에 없으면 메타데이터와 실패 사유만 보존합니다.",
            ],
        },
    }
