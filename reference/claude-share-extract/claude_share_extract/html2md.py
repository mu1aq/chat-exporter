"""Small, dependency-free HTML to Markdown renderer used by the ChatGPT provider.

The archive always retains the source HTML.  This renderer is intentionally a
readable derivative, not the source of truth.  Unlike most HTML normalizers it
keeps literal newlines inside ChatGPT's ``whitespace-pre-wrap`` user bubbles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Optional, Union


@dataclass
class Node:
    tag: str
    attrs: Dict[str, str] = field(default_factory=dict)
    children: List[Union["Node", str]] = field(default_factory=list)
    parent: Optional["Node"] = None


class _Tree(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs) -> None:
        node = Node(tag.lower(), {str(k): str(v or "") for k, v in attrs}, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if node.tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _classes(node: Node) -> List[str]:
    return node.attrs.get("class", "").split()


def _text(node: Union[Node, str]) -> str:
    if isinstance(node, str):
        return node
    return "".join(_text(child) for child in node.children)


def _walk(node: Node, tags: Iterable[str]) -> Iterable[Node]:
    wanted = set(tags)
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if child.tag in wanted:
            yield child
        yield from _walk(child, wanted)


def _fence(text: str) -> str:
    longest = max([len(x) for x in re.findall(r"`+", text)] or [0])
    return "`" * max(3, longest + 1)


def _language(node: Node) -> str:
    values = [node.attrs.get("class", "")]
    values.extend(child.attrs.get("class", "") for child in _walk(node, {"code"}))
    hit = re.search(r"(?:lang(?:uage)?-)([\w.+#-]+)", " ".join(values), re.I)
    return hit.group(1) if hit else ""


def _render_table(node: Node) -> str:
    rows: List[List[str]] = []
    header = 0
    for tr in _walk(node, {"tr"}):
        cells = [c for c in tr.children if isinstance(c, Node) and c.tag in ("th", "td")]
        if not cells:
            continue
        if any(c.tag == "th" for c in cells) and not rows:
            header = 1
        row = [re.sub(r"\s+", " ", _render(c, False).strip()).replace("|", "\\|") for c in cells]
        rows.append(row)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    if not header:
        rows.insert(0, [""] * width)
    lines = ["| " + " | ".join(row) + " |" for row in rows]
    lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n\n" + "\n".join(lines) + "\n\n"


def _render_list(node: Node, ordered: bool, depth: int) -> str:
    lines: List[str] = []
    number = 1
    for child in node.children:
        if not isinstance(child, Node) or child.tag != "li":
            continue
        parts: List[str] = []
        nested: List[Node] = []
        for item in child.children:
            if isinstance(item, Node) and item.tag in ("ul", "ol"):
                nested.append(item)
            else:
                parts.append(_render(item, False))
        body = re.sub(r"[ \t]+", " ", "".join(parts).strip())
        prefix = f"{number}. " if ordered else "- "
        indent = "  " * depth
        body_lines = body.splitlines() or [""]
        lines.append(indent + prefix + body_lines[0])
        lines.extend(indent + "  " + line for line in body_lines[1:])
        for sub in nested:
            lines.append(_render_list(sub, sub.tag == "ol", depth + 1).rstrip("\n"))
        number += 1
    return "\n".join(lines) + "\n"


def _render(node: Union[Node, str], preserve: bool = False) -> str:
    if isinstance(node, str):
        if preserve:
            return node.replace("\r\n", "\n").replace("\r", "\n")
        return re.sub(r"\s+", " ", node)
    tag = node.tag
    if tag in {"script", "style", "noscript", "template", "button", "svg"}:
        return ""
    classes = _classes(node)
    keep = preserve or tag == "pre" or "whitespace-pre-wrap" in classes
    if "katex" in classes or "katex-display" in classes:
        annotation = next((x for x in _walk(node, {"annotation"}) if x.attrs.get("encoding") == "application/x-tex"), None)
        if annotation is not None:
            tex = _text(annotation).strip()
            display = "katex-display" in classes or (node.parent is not None and "katex-display" in _classes(node.parent))
            return f"\n\n$$\n{tex}\n$$\n\n" if display else f"${tex}$"
    if tag == "pre":
        raw = _text(node).replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
        fence = _fence(raw)
        return f"\n\n{fence}{_language(node)}\n{raw}\n{fence}\n\n"
    content = "".join(_render(child, keep) for child in node.children)
    if tag in {"root", "html", "body", "main", "span"}:
        return content
    if tag == "br":
        return "  \n"
    if tag == "hr":
        return "\n\n---\n\n"
    if tag in {"p", "div", "section", "article", "blockquote", "details", "summary"}:
        if "whitespace-pre-wrap" in classes:
            return "\n\n" + content + "\n\n"
        if tag == "blockquote":
            body = "\n".join("> " + line for line in content.strip().splitlines())
            return "\n\n" + body + "\n\n"
        return "\n\n" + content.strip() + "\n\n"
    if re.fullmatch(r"h[1-6]", tag):
        return "\n\n" + "#" * int(tag[1]) + " " + content.strip() + "\n\n"
    if tag in {"strong", "b"}:
        return "**" + content + "**"
    if tag in {"em", "i"}:
        return "*" + content + "*"
    if tag in {"del", "s", "strike"}:
        return "~~" + content + "~~"
    if tag == "code":
        fence = _fence(content)
        return fence + content + fence
    if tag == "a":
        href = node.attrs.get("href", "")
        label = content.strip() or href
        return f"[{label}]({href})" if href else label
    if tag == "img":
        src = node.attrs.get("src", "")
        alt = node.attrs.get("alt", "shared image")
        return f"![{alt}]({src})" if src else f"[image: {alt}]"
    if tag in {"ul", "ol"}:
        return "\n" + _render_list(node, tag == "ol", 0) + "\n"
    if tag == "li":
        return content
    if tag == "table":
        return _render_table(node)
    if tag in {"thead", "tbody", "tfoot", "tr", "th", "td"}:
        return content
    return content


def html_to_markdown(html: str) -> str:
    """Return readable Markdown while preserving pre-wrap text newlines."""
    parser = _Tree()
    parser.feed(str(html or ""))
    parser.close()
    rendered = _render(parser.root).replace("\r\n", "\n").replace("\r", "\n")
    rendered = re.sub(r"\n[ \t]+\n", "\n\n", rendered)
    # Keep two trailing spaces emitted for a Markdown hard break.  Only clean
    # lines that contain no visible characters.
    rendered = re.sub(r"(?m)^[ \t]+$", "", rendered)
    return rendered.strip("\n")


def resource_refs(html: str) -> List[Dict[str, str]]:
    """List media/download references without fetching or silently filtering them."""
    parser = _Tree()
    parser.feed(str(html or ""))
    refs: List[Dict[str, str]] = []
    seen = set()
    for node in _walk(parser.root, {"img", "audio", "video", "source", "a", "iframe", "object"}):
        urls = [node.attrs.get("src") or node.attrs.get("href") or node.attrs.get("data") or ""]
        # Preserve every responsive-image candidate, not just whichever src
        # variant happened to be selected for the current viewport.
        for candidate in (node.attrs.get("srcset") or "").split(","):
            candidate = candidate.strip().split()[0] if candidate.strip() else ""
            if candidate:
                urls.append(candidate)
        for url in urls:
            if not url or (node.tag == "a" and not (node.attrs.get("download") or re.search(r"\.(?:png|jpe?g|gif|webp|svg|pdf|zip|csv|json|txt|docx?|xlsx?|pptx?)(?:[?#]|$)", url, re.I))):
                continue
            key = (node.tag, url)
            if key in seen:
                continue
            seen.add(key)
            refs.append({
                "kind": node.tag,
                "url": url,
                "name": node.attrs.get("download") or node.attrs.get("alt") or node.attrs.get("title") or "",
                "mime": node.attrs.get("type") or "",
            })
    return refs


__all__ = ["html_to_markdown", "resource_refs"]
