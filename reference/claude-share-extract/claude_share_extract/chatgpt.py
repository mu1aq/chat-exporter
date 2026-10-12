"""Loss-aware ChatGPT public-share capture and normalization.

The provider keeps raw DOM, structured payloads, response metadata and media
bytes whenever they are exposed to the public browser context.  Human-readable
Markdown is a derivative; raw capture data remains the archive source of truth.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import mimetypes
import re
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote_to_bytes, urljoin, urlsplit, urlunsplit

from .html2md import html_to_markdown, resource_refs

CHATGPT_HOST = "chatgpt.com"
_SHARE_ID = re.compile(r"^[A-Za-z0-9_-]{8,200}$")
_ROLES = {"user", "assistant", "system", "developer", "tool"}
_MEDIA_MIME = re.compile(r"^(?:image|audio|video)/|^(?:application/pdf|application/octet-stream)", re.I)
_JSON_MIME = re.compile(r"(?:^|/|\+)json(?:;|$)", re.I)
_BLOCKED = [
    re.compile(x, re.I) for x in (
        r"conversation (?:is )?(?:unavailable|not found)",
        r"shared link (?:has been )?(?:deleted|disabled|expired)",
        r"you (?:do not|don't) have access",
        r"workspace.*(?:access|member|permission)",
        r"sign in to (?:view|continue)",
        r"unable to load (?:conversation|shared)",
        r"something went wrong",
    )
]


class ChatGPTError(RuntimeError):
    pass


class ChatGPTBrowserUnavailable(ChatGPTError):
    pass


def validate_chatgpt_url(value: str) -> str:
    """Strictly validate and canonicalize a public ChatGPT share URL."""
    raw = str(value or "").strip().strip("<>\"'")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except (TypeError, ValueError) as exc:
        raise ValueError("Expected https://chatgpt.com/share/<conversation-id>") from exc
    if parts.scheme.lower() != "https":
        raise ValueError("Only HTTPS ChatGPT share links are accepted.")
    if (parts.hostname or "").lower() != CHATGPT_HOST:
        raise ValueError("Only the chatgpt.com host is accepted.")
    if port is not None or parts.username or parts.password:
        raise ValueError("Ports and URL credentials are not accepted.")
    match = re.fullmatch(r"/share/([^/]+)/?", parts.path)
    if not match or not _SHARE_ID.fullmatch(match.group(1)):
        raise ValueError("Expected https://chatgpt.com/share/<conversation-id>")
    return urlunsplit(("https", CHATGPT_HOST, "/share/" + match.group(1), "", ""))


def chatgpt_share_id(value: str) -> str:
    return urlsplit(validate_chatgpt_url(value)).path.rsplit("/", 1)[-1]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()


def _compare_text(value: Any) -> str:
    # Rendering removes Markdown punctuation.  Ignore it only for cross-checks;
    # the archived source and selected output are never modified this way.
    return re.sub(r"[\s*_`>#~\[\]()-]+", "", str(value or "")).casefold()


def _content_blocks(content: Any) -> List[Dict[str, Any]]:
    """Normalize known block text while retaining every raw block."""
    if isinstance(content, str):
        return [{"type": "text", "text": content, "raw": content}]
    if not isinstance(content, dict):
        return [{"type": "unknown", "raw": copy.deepcopy(content)}] if content is not None else []
    parts = content.get("parts")
    if not isinstance(parts, list):
        if isinstance(content.get("text"), str):
            return [{"type": "text", "text": content["text"], "raw": copy.deepcopy(content)}]
        return [{"type": str(content.get("content_type") or "unknown"), "raw": copy.deepcopy(content)}]
    blocks: List[Dict[str, Any]] = []
    for part in parts:
        if isinstance(part, str):
            blocks.append({"type": "text", "text": part, "raw": part})
            continue
        if not isinstance(part, dict):
            blocks.append({"type": "unknown", "raw": copy.deepcopy(part)})
            continue
        block = copy.deepcopy(part)
        kind = str(part.get("content_type") or part.get("type") or "unknown")
        text = part.get("text") if isinstance(part.get("text"), str) else part.get("content")
        out: Dict[str, Any] = {"type": kind, "raw": block}
        if isinstance(text, str):
            out["text"] = text
        target = part.get("image_url") or part.get("url") or part.get("asset_pointer")
        if isinstance(target, dict):
            target = target.get("url")
        if isinstance(target, str):
            out["url"] = target
        blocks.append(out)
    return blocks


def _message_from_node(node: Dict[str, Any], node_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if "message" in node:
        if not isinstance(node.get("message"), dict):
            return None
        message = node["message"]
    else:
        message = node
    if not isinstance(message, dict):
        return None
    author = message.get("author") if isinstance(message.get("author"), dict) else {}
    role = str(author.get("role") or message.get("role") or "unknown")
    blocks = _content_blocks(message.get("content", message))
    text = "\n".join(str(b.get("text", "")) for b in blocks if isinstance(b.get("text"), str))
    return {
        "uuid": message.get("id") or node_id,
        "node_id": node_id,
        "parent": node.get("parent") if isinstance(node, dict) else None,
        "children": copy.deepcopy(node.get("children") or []) if isinstance(node, dict) else [],
        "role": role,
        "author": copy.deepcopy(author),
        "created_at": message.get("create_time", message.get("createTime")),
        "updated_at": message.get("update_time", message.get("updateTime")),
        "status": message.get("status"),
        "recipient": message.get("recipient"),
        "text": text,
        "blocks": blocks,
        "metadata": copy.deepcopy(message.get("metadata") or {}),
        "raw": copy.deepcopy(message),
    }


def _mapping_candidate(value: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    mapping = value.get("mapping")
    if not isinstance(mapping, dict) or not mapping:
        return None
    ids = list(mapping)
    parent_ids = {str(n.get("parent")) for n in mapping.values() if isinstance(n, dict) and n.get("parent")}
    leaves = [node_id for node_id in ids if node_id not in parent_ids]
    active_leaf = value.get("current_node") or value.get("currentNode")
    if active_leaf not in mapping:
        active_leaf = leaves[-1] if leaves else ids[-1]

    def path_to(leaf: str) -> List[str]:
        path: List[str] = []
        seen = set()
        current: Optional[str] = leaf
        while current and current in mapping and current not in seen:
            seen.add(current)
            path.append(current)
            item = mapping[current]
            current = item.get("parent") if isinstance(item, dict) else None
        path.reverse()
        return path

    branch_leaves = list(leaves)
    if active_leaf not in branch_leaves:
        branch_leaves.append(active_leaf)
    branches = []
    for index, leaf in enumerate(branch_leaves or [active_leaf]):
        node_ids = path_to(leaf)
        messages = []
        for node_id in node_ids:
            raw_node = mapping.get(node_id)
            if isinstance(raw_node, dict):
                msg = _message_from_node(raw_node, node_id)
                if msg is not None:
                    messages.append(msg)
        branches.append({
            "id": str(leaf),
            "leaf_id": str(leaf),
            "is_active": leaf == active_leaf,
            "node_ids": node_ids,
            "messages": messages,
            "index": index,
        })
    active = next((b for b in branches if b["is_active"]), branches[-1] if branches else None)
    all_messages = []
    for node_id, raw_node in mapping.items():
        if isinstance(raw_node, dict):
            msg = _message_from_node(raw_node, str(node_id))
            if msg is not None:
                all_messages.append(msg)
    return {
        "title": value.get("title"),
        "messages": active["messages"] if active else [],
        "all_messages": all_messages,
        "branches": branches,
        "active_branch_id": active["id"] if active else None,
        "score": len(all_messages) * 10 + len(active["messages"] if active else []),
        "raw": copy.deepcopy(value),
    }


def _array_candidate(value: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("messages", "conversation", "data"):
        nested = value.get(key)
        if not isinstance(nested, list):
            continue
        messages = []
        for index, raw in enumerate(nested):
            if isinstance(raw, dict):
                msg = _message_from_node(raw, str(raw.get("id") or index))
                if msg is not None and (msg["role"] in _ROLES or msg["text"] or msg["blocks"]):
                    messages.append(msg)
        if messages:
            branch = {"id": "active", "leaf_id": None, "is_active": True,
                      "node_ids": [m.get("node_id") for m in messages], "messages": messages, "index": 0}
            return {"title": value.get("title"), "messages": messages, "all_messages": messages,
                    "branches": [branch], "active_branch_id": "active", "score": len(messages),
                    "raw": copy.deepcopy(value)}
    return None


def find_structured_conversation(root: Any) -> Optional[Dict[str, Any]]:
    """Find the strongest conversation-shaped object without discarding branches."""
    queue = deque([root])
    seen = set()
    best = None
    while queue and len(seen) < 50000:
        value = queue.popleft()
        if not isinstance(value, (dict, list)) or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, dict):
            candidate = _mapping_candidate(value) or _array_candidate(value)
            if candidate and (best is None or candidate["score"] > best["score"]):
                best = candidate
            children: Iterable[Any] = value.values()
        else:
            children = value
        queue.extend(child for child in children if isinstance(child, (dict, list)))
    return best


def parse_json_scripts(scripts: Iterable[str]) -> List[Any]:
    values = []
    for script in scripts:
        text = str(script or "").strip()
        if not text:
            continue
        attempts = [text]
        first, last = text.find("{"), text.rfind("}")
        if first >= 0 and last > first:
            attempts.append(text[first:last + 1])
        for attempt in attempts:
            try:
                values.append(json.loads(attempt))
                break
            except (TypeError, ValueError):
                continue
    return values


def _record_key(record: Dict[str, Any]) -> str:
    return str(record.get("source_id") or "\0".join([
        str(record.get("role") or ""), str(record.get("turn_index") or ""),
        str(record.get("plain_text") or ""), str(record.get("html") or ""),
    ]))


def _collect_current(page) -> List[Dict[str, Any]]:
    # Take one atomic browser-side snapshot.  Iterating Locator.nth() races with
    # React virtualization: a turn can detach between count() and evaluation,
    # causing a full timeout and losing the archive.
    records = page.evaluate(r"""() => {
      const selector = '[data-message-author-role="user"], [data-message-author-role="assistant"]';
      const direct = [...document.querySelectorAll(selector)].filter(el => !el.parentElement?.closest(selector));
      const make = (el, source) => {
        const turn = el.closest('[data-testid^="conversation-turn-"]');
        const turnTestId = turn?.getAttribute('data-testid') || '';
        const match = turnTestId.match(/conversation-turn-(\d+)/);
        const msg = el.closest('[data-message-id]');
        // Long user prompts get a Show more/Show less button inside the
        // message element.  Read the dedicated content node so those UI
        // labels never become part of the user's literal input.  Keep the
        // complete outer HTML separately as raw evidence.
        let content = el;
        if (el.getAttribute('data-message-author-role') === 'user') {
          content = el.querySelector('[data-testid="collapsible-user-message-content"]')
            || el.querySelector('.whitespace-pre-wrap') || el;
        } else {
          content = el.querySelector('.markdown') || el;
        }
        return {
          role: el.getAttribute('data-message-author-role'),
          source_id: msg?.getAttribute('data-message-id') || el.getAttribute('data-message-id'),
          turn_index: match ? Number(match[1]) : null,
          turn_test_id: turnTestId,
          html: content.innerHTML,
          outer_html: el.outerHTML,
          plain_text: content.innerText || content.textContent || '',
          text_content: content.textContent || '',
          source,
        };
      };
      if (direct.length) return direct.map(el => make(el, 'dom-role-attribute'));
      return [...document.querySelectorAll('[data-testid^="conversation-turn-"]')].map(turn => {
        const explicit = turn.querySelector(selector);
        const label = `${turn.getAttribute('aria-label') || ''} ${(turn.innerText || '').slice(0,120)}`.toLowerCase();
        let role = explicit?.getAttribute('data-message-author-role') || null;
        if (!role && (/\byou said\b|\buser\b/).test(label)) role = 'user';
        if (!role && (/\bchatgpt said\b|\bassistant\b/).test(label)) role = 'assistant';
        if (!role) return null;
        const rec = make(explicit || turn, 'dom-turn-article');
        rec.role = role;
        rec.source_id ||= turn.getAttribute('data-message-id') || turn.getAttribute('data-testid');
        return rec;
      }).filter(Boolean);
    }""")
    for record in records:
        record["resources"] = resource_refs(record.get("html") or "")
    return records


def _scroll_state(page, target: Optional[Any] = None) -> Dict[str, float]:
    return page.evaluate("""target => {
      const role = document.querySelector('[data-message-author-role="user"], [data-message-author-role="assistant"]');
      let s = role?.parentElement || null;
      while (s) { const st = getComputedStyle(s); if (s.scrollHeight > s.clientHeight + 20 && /auto|scroll/.test(st.overflowY)) break; s = s.parentElement; }
      s ||= document.scrollingElement;
      if (!s) return {top:0,height:0,client:0};
      if (target === 'top') s.scrollTop = 0; else if (target === 'bottom') s.scrollTop = s.scrollHeight;
      else if (typeof target === 'number') s.scrollTop = target;
      return {top:s.scrollTop,height:s.scrollHeight,client:s.clientHeight};
    }""", target)


def _response_entry(response, max_asset_bytes: int) -> Dict[str, Any]:
    try:
        headers = response.all_headers()
    except Exception:
        headers = {}
    mime = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    entry: Dict[str, Any] = {
        "url": response.url, "status": response.status, "mime": mime,
        "resource_type": response.request.resource_type,
        "headers": {k: v for k, v in headers.items() if k.lower() in {
            "content-type", "content-length", "content-disposition", "etag", "last-modified", "cache-control"
        }},
    }
    if not (_JSON_MIME.search(mime) or _MEDIA_MIME.search(mime)):
        return entry
    try:
        announced = int(headers.get("content-length", "0") or 0)
    except ValueError:
        announced = 0
    if announced > max_asset_bytes:
        entry.update({"captured": False, "reason": "content-length exceeds capture limit", "size": announced})
        return entry
    try:
        body = response.body()
    except Exception as exc:
        entry.update({"captured": False, "reason": "response body unavailable: " + str(exc)[:160]})
        return entry
    entry.update({"size": len(body), "sha256": _sha(body)})
    if len(body) > max_asset_bytes:
        entry.update({"captured": False, "reason": "response body exceeds capture limit"})
    elif _JSON_MIME.search(mime):
        text = body.decode("utf-8", errors="replace")
        entry.update({"captured": True, "text": text,
                      "body_base64": base64.b64encode(body).decode("ascii")})
        try:
            entry["json"] = json.loads(text)
        except ValueError:
            pass
    else:
        entry.update({"captured": True, "body_base64": base64.b64encode(body).decode("ascii")})
    return entry


def _data_url(url: str) -> Optional[Tuple[bytes, str]]:
    if not url.startswith("data:") or "," not in url:
        return None
    meta, payload = url[5:].split(",", 1)
    mime = meta.split(";", 1)[0] or "application/octet-stream"
    try:
        body = base64.b64decode(payload) if ";base64" in meta else unquote_to_bytes(payload)
    except Exception:
        return None
    return body, mime


def _assets_from_capture(page, refs: List[Dict[str, str]], responses: List[Dict[str, Any]],
                         max_asset_bytes: int) -> List[Dict[str, Any]]:
    captured = {r.get("url"): r for r in responses if r.get("body_base64")}
    assets: List[Dict[str, Any]] = []
    seen = set()
    for ref in refs:
        original_url = ref.get("url") or ""
        url = urljoin(page.url, original_url) if original_url and not original_url.startswith(("data:", "blob:")) else original_url
        if not url or url in seen:
            continue
        seen.add(url)
        item: Dict[str, Any] = dict(ref)
        item["url"] = url
        if url != original_url:
            item["original_url"] = original_url
        item.update({"id": "asset-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16], "fetched": False})
        hit = captured.get(url)
        if hit:
            item.update({"fetched": True, "mime": hit.get("mime") or item.get("mime"), "size": hit.get("size"),
                         "sha256": hit.get("sha256"), "content_base64": hit.get("body_base64"),
                         "capture_method": "browser-response"})
            assets.append(item)
            continue
        parsed = _data_url(url)
        if parsed:
            body, mime = parsed
            if len(body) <= max_asset_bytes:
                item.update({"fetched": True, "mime": mime, "size": len(body), "sha256": _sha(body),
                             "content_base64": base64.b64encode(body).decode("ascii"), "capture_method": "data-url"})
            else:
                item["reason"] = "data URL exceeds capture limit"
            assets.append(item)
            continue
        if url.startswith("blob:"):
            try:
                result = page.evaluate("""async ({u,limit}) => { const r=await fetch(u); const blob=await r.blob();
                  if(blob.size>limit) return {mime:blob.type||'',size:blob.size,tooLarge:true};
                  const b=new Uint8Array(await blob.arrayBuffer());
                  let s=''; const step=32768; for(let i=0;i<b.length;i+=step) s += String.fromCharCode(...b.subarray(i,i+step));
                  return {mime:blob.type||r.headers.get('content-type')||'', data:btoa(s), size:b.length}; }""",
                                       {"u": url, "limit": max_asset_bytes})
                if not result.get("tooLarge") and int(result.get("size") or 0) <= max_asset_bytes:
                    body = base64.b64decode(result["data"])
                    item.update({"fetched": True, "mime": result.get("mime") or item.get("mime"), "size": len(body),
                                 "sha256": _sha(body), "content_base64": result["data"], "capture_method": "blob-fetch"})
                else:
                    item["reason"] = "blob exceeds capture limit"
            except Exception as exc:
                item["reason"] = "blob fetch failed: " + str(exc)[:160]
            assets.append(item)
            continue
        if url.startswith(("http://", "https://")):
            try:
                res = page.context.request.get(url, headers={"Range": f"bytes=0-{max_asset_bytes}"}, timeout=15000)
                body = res.body()
                mime = str(res.headers.get("content-type") or item.get("mime") or "").split(";", 1)[0]
                if res.ok and len(body) <= max_asset_bytes:
                    item.update({"fetched": True, "mime": mime, "size": len(body), "sha256": _sha(body),
                                 "content_base64": base64.b64encode(body).decode("ascii"),
                                 "capture_method": "context-request"})
                else:
                    item["reason"] = f"download returned HTTP {res.status} or exceeded capture limit"
            except Exception as exc:
                item["reason"] = "download failed: " + str(exc)[:160]
        else:
            item["reason"] = "unsupported or private asset pointer"
        assets.append(item)
    return assets


def capture_chatgpt(url: str, *, timeout: float = 60.0, channel: Optional[str] = None,
                    executable: Optional[str] = None, headless: bool = True,
                    screenshot: bool = False, max_asset_bytes: int = 50 * 1024 * 1024) -> Dict[str, Any]:
    """Capture a public share with virtualized turns, raw payloads and media."""
    source_url = validate_chatgpt_url(url)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise ChatGPTBrowserUnavailable(
            "Playwright is required for ChatGPT shares. Install: pip install '.[browser]'"
        ) from exc
    timeout_ms = max(1000, int(timeout * 1000))
    deadline = time.monotonic() + timeout
    playwright = sync_playwright().start()
    browser = None
    responses: List[Dict[str, Any]] = []
    try:
        launch: Dict[str, Any] = {"headless": headless}
        if executable:
            launch["executable_path"] = executable
        elif channel and channel != "chromium":
            launch["channel"] = channel
        try:
            browser = playwright.chromium.launch(**launch)
        except PlaywrightError as exc:
            raise ChatGPTBrowserUnavailable(
                "Could not launch Chromium. Run `playwright install chromium` or use --browser-channel chrome."
            ) from exc
        context = browser.new_context(locale="en-US", service_workers="block")
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        def on_response(response) -> None:
            try:
                responses.append(_response_entry(response, max_asset_bytes))
            except Exception:
                responses.append({"url": getattr(response, "url", ""), "captured": False,
                                  "reason": "response callback failed"})

        page.on("response", on_response)
        nav = page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
        if nav is None:
            raise ChatGPTError("Navigation produced no HTTP response.")
        if nav.status >= 400:
            raise ChatGPTError(f"The shared page returned HTTP {nav.status}.")
        try:
            final_url = validate_chatgpt_url(page.url)
        except ValueError as exc:
            raise ChatGPTError(f"Share redirected outside a public ChatGPT page: {page.url}") from exc
        try:
            page.wait_for_selector('[data-message-author-role="user"], [data-message-author-role="assistant"]',
                                   state="attached", timeout=min(timeout_ms, 20000))
        except PlaywrightError:
            # Validation below distinguishes a slow/layout failure from a known blocked page.
            pass

        collected: Dict[str, Dict[str, Any]] = {}
        observations: List[int] = []
        unique_counts: List[int] = []

        def sample() -> None:
            current = _collect_current(page)
            observations.append(len(current))
            for record in current:
                if _record_key(record) not in collected:
                    record["collection_order"] = len(collected)
                collected[_record_key(record)] = record
            unique_counts.append(len(collected))

        sample()
        toc_values = page.locator("[data-toc-item-index]").evaluate_all(
            "els => [...new Set(els.map(e => Number(e.getAttribute('data-toc-item-index'))).filter(Number.isFinite))].sort((a,b)=>a-b)")
        visited = 0
        for item_index in toc_values:
            if time.monotonic() >= deadline:
                break
            try:
                clicked = page.evaluate("""i => {
                  const el = document.querySelector(`[data-toc-item-index="${i}"]`);
                  if (!el) return false; el.click(); return true;
                }""", item_index)
                if not clicked:
                    continue
                visited += 1
            except PlaywrightError:
                continue
            last = None
            stable = 0
            for _ in range(10):
                page.wait_for_timeout(100)
                sample()
                now = tuple((_record_key(r) for r in _collect_current(page)))
                stable = stable + 1 if now == last else 0
                last = now
                if stable >= 1:
                    break

        if not toc_values or len(collected) < len(toc_values) * 2:
            state = _scroll_state(page, "top")
            page.wait_for_timeout(200)
            unchanged = 0
            for _ in range(500):
                if time.monotonic() >= deadline:
                    break
                before = len(collected)
                sample()
                unchanged = unchanged + 1 if before == len(collected) else 0
                state = _scroll_state(page)
                at_bottom = state["top"] + state["client"] >= state["height"] - 2
                if at_bottom and unchanged >= 3:
                    break
                increment = max(300, state["client"] * 0.8)
                _scroll_state(page, min(state["height"], state["top"] + increment))
                page.wait_for_timeout(150)

        records = list(collected.values())
        if records and all(isinstance(r.get("turn_index"), int) for r in records):
            indexes = [r["turn_index"] for r in records]
            if len(indexes) == len(set(indexes)):
                records.sort(key=lambda r: r["turn_index"])
        scripts = page.locator('script[type="application/json"], script#__NEXT_DATA__').all_text_contents()
        body_text = page.locator("body").inner_text()[:100000]
        document_title = page.title()
        try:
            og_title = page.locator('meta[property="og:title"]').get_attribute("content") or ""
        except Exception:
            og_title = ""
        title = re.sub(r"\s*[|–-]\s*ChatGPT\s*$", "", document_title, flags=re.I).strip()
        if title in {"ChatGPT", "Check out this chat", "Shared Chat"}:
            title = og_title.strip()
        refs = []
        for record in records:
            refs.extend(record.get("resources") or [])
        assets = _assets_from_capture(page, refs, responses, max_asset_bytes)
        shot = None
        if screenshot:
            try:
                shot_bytes = page.screenshot(full_page=True)
                shot = {"mime": "image/png", "size": len(shot_bytes), "sha256": _sha(shot_bytes),
                        "content_base64": base64.b64encode(shot_bytes).decode("ascii"),
                        "warning": "Virtualized pages may not render every collected turn in one screenshot."}
            except PlaywrightError as exc:
                shot = {"error": str(exc)}
        html = page.content()
        return {
            "provider": "chatgpt", "source_url": source_url, "final_url": final_url,
            "http_status": nav.status, "title": title or og_title or "ChatGPT shared conversation",
            "document_language": page.locator("html").get_attribute("lang"),
            "records": records, "scripts": scripts, "body_text": body_text, "page_html": html,
            "responses": responses, "assets": assets, "screenshot": shot,
            "observations": observations, "traversal": {
                "toc_prompt_count": len(toc_values), "toc_prompts_visited": visited,
                "unique_message_counts": unique_counts, "deadline_reached": time.monotonic() >= deadline,
            },
        }
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        playwright.stop()


def _structured_from_capture(capture: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    candidates = []
    for response in capture.get("responses") or []:
        value = response.get("json")
        if value is None and isinstance(response.get("text"), str):
            try:
                value = json.loads(response["text"])
            except ValueError:
                continue
        found = find_structured_conversation(value)
        if found:
            candidates.append(found)
    for value in parse_json_scripts(capture.get("scripts") or []):
        found = find_structured_conversation(value)
        if found:
            candidates.append(found)
    return max(candidates, key=lambda c: c["score"]) if candidates else None


def _dom_message(record: Dict[str, Any]) -> Dict[str, Any]:
    # User bubbles rely on CSS pre-wrap; inner_text is the faithful readable
    # derivative.  Raw HTML + textContent are retained for exact reprocessing.
    role = record.get("role") or "unknown"
    text = record.get("plain_text") if role == "user" else html_to_markdown(record.get("html") or "")
    return {
        "uuid": record.get("source_id"), "node_id": record.get("turn_test_id"),
        "role": role, "created_at": None, "text": text or "",
        "blocks": [{"type": "text", "text": text or "", "raw_html": record.get("html") or ""}],
        "plain_text": record.get("plain_text") or "", "text_content": record.get("text_content") or "",
        "raw_html": record.get("outer_html") or "", "resources": copy.deepcopy(record.get("resources") or []),
        "turn_index": record.get("turn_index"), "source": record.get("source"),
    }


def _visible(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [m for m in messages if m.get("role") in {"user", "assistant"}]


def _turns(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    turns: List[Dict[str, Any]] = []
    current = None
    for message in messages:
        role = message.get("role")
        if role == "user":
            current = {"turn": len(turns) + 1, "user_input": message.get("text") or "", "agent_output": "",
                       "user_at": message.get("created_at"), "agent_at": None, "attachments": [],
                       "tool_call_count": 0, "message_ids": [message.get("uuid")]}
            turns.append(current)
        elif role == "assistant":
            if current is None:
                current = {"turn": len(turns) + 1, "user_input": "", "agent_output": "",
                           "user_at": None, "agent_at": None, "attachments": [], "tool_call_count": 0,
                           "message_ids": []}
                turns.append(current)
            if current["agent_output"] and message.get("text"):
                current["agent_output"] += "\n\n"
            current["agent_output"] += message.get("text") or ""
            current["agent_at"] = message.get("created_at") or current["agent_at"]
            current["message_ids"].append(message.get("uuid"))
    return turns


def _artifacts(structured: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not structured:
        return []
    out = []
    for message in structured.get("all_messages") or []:
        author = message.get("author") or {}
        name = str(author.get("name") or message.get("recipient") or "")
        metadata = message.get("metadata") or {}
        artifactish = bool(re.search(r"artifact|canmore|canvas|textdoc", name, re.I)) or any(
            re.search(r"artifact|canvas|textdoc", str(key), re.I) for key in metadata)
        artifact_blocks = [b for b in message.get("blocks") or [] if re.search(
            r"artifact|canvas|textdoc", str(b.get("type") or ""), re.I)]
        if artifactish or artifact_blocks:
            version = {"version": 1, "action": "captured", "message_id": message.get("uuid"),
                       "content": message.get("text") or "", "blocks": copy.deepcopy(message.get("blocks") or []),
                       "raw": copy.deepcopy(message.get("raw")), "ext": "txt"}
            out.append({
                "key": str(message.get("uuid") or "artifact-" + str(len(out) + 1)),
                "title": str(metadata.get("title") or name or "ChatGPT artifact"),
                "versions": 1, "history": [version],
                "content": message.get("text") or "", "ext": "txt", "language": "", "type": "",
            })
    return out


def extract_chatgpt(capture: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw browser capture without discarding unrecognized data."""
    dom_messages = [_dom_message(record) for record in capture.get("records") or []]
    structured = _structured_from_capture(capture)
    structured_visible = _visible(structured.get("messages") or []) if structured else []
    warnings: List[str] = []
    use_structured = False
    if structured_visible and len(structured_visible) == len(dom_messages):
        same_roles = [m.get("role") for m in structured_visible] == [m.get("role") for m in dom_messages]
        same_text = same_roles and all(
            _compare_text(a.get("text")) == _compare_text(b.get("plain_text") or b.get("text"))
            for a, b in zip(structured_visible, dom_messages)
        )
        use_structured = same_roles and same_text
        if same_roles and not same_text:
            warnings.append("Structured data matched DOM roles/counts but not message text; rendered DOM was selected.")
    elif structured_visible and dom_messages:
        warnings.append(f"DOM found {len(dom_messages)} visible messages; structured data found {len(structured_visible)}.")
    messages = structured_visible if use_structured else dom_messages
    body = capture.get("body_text") or ""
    if not messages:
        known = any(pattern.search(body) for pattern in _BLOCKED)
        warnings.append("No messages were found; the page is unavailable/restricted or its layout changed."
                        if known else "No messages were found; the layout may have changed or rendering was incomplete.")
    for index, message in enumerate(messages, 1):
        if not _norm(message.get("text")):
            warnings.append(f"Message {index} ({message.get('role')}) is empty after conversion.")
    traversal = capture.get("traversal") or {}
    user_count = sum(1 for m in messages if m.get("role") == "user")
    toc_count = int(traversal.get("toc_prompt_count") or 0)
    if toc_count and toc_count != user_count:
        warnings.append(f"Possible omission: {toc_count} prompt markers but {user_count} user messages were collected.")
    if traversal.get("deadline_reached"):
        warnings.append("Virtualized-message traversal reached its deadline.")
    branch_list = copy.deepcopy(structured.get("branches") or []) if structured else [{
        "id": "rendered-dom", "leaf_id": None, "is_active": True,
        "node_ids": [m.get("node_id") for m in dom_messages], "messages": copy.deepcopy(dom_messages), "index": 0,
    }]
    active_ids = set()
    for branch in branch_list:
        if branch.get("is_active"):
            active_ids.update(x for x in branch.get("node_ids") or [] if x)
    all_for_branches = copy.deepcopy(structured.get("all_messages") or dom_messages) if structured else copy.deepcopy(dom_messages)
    branch_nodes = [{
        "uuid": m.get("node_id") or m.get("uuid"), "parent_uuid": m.get("parent"),
        "index": m.get("turn_index"), "role": m.get("role"), "created_at": m.get("created_at"),
        "is_active": (m.get("node_id") or m.get("uuid")) in active_ids, "message": m,
    } for m in all_for_branches]
    branches = {
        "active_leaf_uuid": (structured or {}).get("active_branch_id") or "rendered-dom",
        "linked": bool(structured), "nodes": branch_nodes,
        "paths": [{
            "leaf_uuid": b.get("leaf_id") or b.get("id"), "is_active": bool(b.get("is_active")),
            "length": len(b.get("node_ids") or []), "message_uuids": list(b.get("node_ids") or []),
            "messages": b.get("messages") or [],
        } for b in branch_list],
    }
    assets = copy.deepcopy(capture.get("assets") or [])
    uncertain = [
        {"item": "hidden-or-server-only-data", "reason": "A public share cannot expose data the service did not send."},
        {"item": "rendered-markdown", "reason": "Markdown is derived; raw message HTML/text is retained."},
    ]
    for asset in assets:
        if not asset.get("fetched"):
            uncertain.append({"item": asset.get("url") or asset.get("id"),
                              "reason": asset.get("reason") or "Referenced asset was not downloadable."})
    sid = chatgpt_share_id(capture.get("source_url"))
    turns = _turns(messages)
    return {
        "provider": "chatgpt",
        "source": {
            "provider": "chatgpt", "share_id": sid, "share_url": capture.get("source_url"),
            "final_url": capture.get("final_url"), "title": (structured or {}).get("title") or capture.get("title") or "",
            "created_at": None, "updated_at": None,
        },
        "options": {"lossless_archive": True}, "turns": turns, "messages": messages,
        "all_messages": copy.deepcopy(structured.get("all_messages") or dom_messages) if structured else copy.deepcopy(dom_messages),
        "branches": branches, "active_branch_id": (structured or {}).get("active_branch_id") or "rendered-dom",
        "artifacts": _artifacts(structured), "assets": assets,
        "stats": {
            "turns": len(turns), "messages": len(messages),
            "messages_in_source": len((structured or {}).get("all_messages") or dom_messages),
            "messages_in_snapshot": len((structured or {}).get("all_messages") or dom_messages),
            "user_chars": sum(len(t["user_input"]) for t in turns),
            "assistant_chars": sum(len(t["agent_output"]) for t in turns),
            "tool_calls": {}, "attachments": len(assets), "artifacts": len(_artifacts(structured)),
            "thinking_blocks": sum(1 for m in (structured or {}).get("all_messages") or []
                                   for b in m.get("blocks") or [] if "thinking" in str(b.get("type"))),
        },
        "warnings": warnings,
        "preservation": {
            "captured": ["rendered messages", "raw per-message HTML", "page HTML", "network JSON/media metadata",
                         "all exposed structured branches", "downloadable referenced assets"],
            "dropped": [], "uncertain": uncertain,
        },
        "capture": copy.deepcopy(capture),
    }


def capture_and_extract(url: str, **options: Any) -> Dict[str, Any]:
    return extract_chatgpt(capture_chatgpt(url, **options))


__all__ = [
    "ChatGPTError", "ChatGPTBrowserUnavailable", "validate_chatgpt_url", "chatgpt_share_id",
    "find_structured_conversation", "parse_json_scripts", "capture_chatgpt", "extract_chatgpt",
    "capture_and_extract",
]
