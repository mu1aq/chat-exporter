"""Reconstruct file versions from OpenAI ``apply_patch`` blocks (Codex).

Codex applies edits by running a patch in an ``exec`` tool call; the patch text
is embedded in the call input as a JS string literal:

    *** Begin Patch
    *** Add File: path            +lines...
    *** Update File: path         @@ / context / -removed / +added
    *** Delete File: path
    *** End Patch

:func:`reconstruct` scans session tool-call inputs in order, applies each patch
to running file state, and returns artifact dicts (same shape ``bundle`` uses).
Hunks are located by matching context+removed lines; an unmatched hunk is
reported, not fabricated, and leaves the file unchanged.
"""

from __future__ import annotations

import posixpath
from typing import Any, Dict, List, Optional, Tuple

_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_EXT = {"py": "python", "js": "javascript", "ts": "typescript", "md": "markdown", "json": "json",
        "html": "html", "css": "css", "sh": "bash", "yml": "yaml", "yaml": "yaml", "toml": "toml"}


def _js_unescape(s: str) -> str:
    out: List[str] = []
    i = 0
    simple = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\", "/": "/", "b": "\b", "f": "\f"}
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "u" and i + 5 < len(s):
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            out.append(simple.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def extract_patches(text: str) -> List[str]:
    """Return each Begin/End patch block found in ``text`` (JS-unescaped)."""
    if not isinstance(text, str) or _BEGIN not in text:
        return []
    patches: List[str] = []
    start = 0
    while True:
        a = text.find(_BEGIN, start)
        if a < 0:
            break
        b = text.find(_END, a)
        if b < 0:
            break
        patches.append(_js_unescape(text[a:b + len(_END)]))
        start = b + len(_END)
    return patches


def parse_patch(patch: str) -> List[Dict[str, Any]]:
    ops: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for line in patch.split("\n"):
        if line.startswith(_BEGIN) or line.startswith(_END):
            continue
        if line.startswith("*** Add File: "):
            cur = {"action": "add", "path": line[len("*** Add File: "):].strip(), "lines": []}
            ops.append(cur)
        elif line.startswith("*** Update File: "):
            cur = {"action": "update", "path": line[len("*** Update File: "):].strip(), "hunk": []}
            ops.append(cur)
        elif line.startswith("*** Delete File: "):
            ops.append({"action": "delete", "path": line[len("*** Delete File: "):].strip()})
            cur = None
        elif line.startswith("*** "):  # e.g. *** Move to: (ignored for content)
            continue
        elif cur and cur["action"] == "add":
            if line.startswith("+"):
                cur["lines"].append(line[1:])
        elif cur and cur["action"] == "update":
            cur["hunk"].append(line)
    return ops


def _apply_update(old: str, hunk: List[str]) -> Tuple[str, bool]:
    lines = old.split("\n")
    pos = 0
    ok = True
    for raw in _split_hunks(hunk):
        want = [ln[1:] if ln and ln[0] in " -+" else ln for ln in raw if not (ln and ln[0] == "+")]
        repl = [ln[1:] if ln and ln[0] in " -+" else ln for ln in raw if not (ln and ln[0] == "-")]
        at = _find(lines, want, pos)
        if at < 0:
            ok = False
            continue
        lines[at:at + len(want)] = repl
        pos = at + len(repl)
    return "\n".join(lines), ok


def _split_hunks(hunk: List[str]) -> List[List[str]]:
    groups: List[List[str]] = []
    cur: List[str] = []
    for ln in hunk:
        if ln.startswith("@@"):
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(ln)
    if cur:
        groups.append(cur)
    return groups or [[]]


def _find(hay: List[str], needle: List[str], start: int) -> int:
    if not needle:
        return start
    for i in range(start, len(hay) - len(needle) + 1):
        if hay[i:i + len(needle)] == needle:
            return i
    return -1


class _Reconstructor:
    def __init__(self) -> None:
        self.files: Dict[str, Dict[str, Any]] = {}
        self.order: List[str] = []
        self.failures = 0

    def _ext(self, path: str) -> str:
        name = posixpath.basename(path.replace("\\", "/"))
        return name.rsplit(".", 1)[1].lower() if "." in name else "txt"

    def _bump(self, path: str, content: str, action: str) -> None:
        f = self.files.get(path)
        if f is None:
            ext = self._ext(path)
            f = {"key": path, "title": path, "type": "", "language": _EXT.get(ext, ""), "ext": ext,
                 "content": content, "versions": 0, "history": []}
            self.files[path] = f
            self.order.append(path)
        f["content"] = content
        f["versions"] += 1
        f["history"].append({"version": f["versions"], "action": action, "content": content, "ext": f["ext"]})

    def feed(self, patch_text: str) -> None:
        for op in parse_patch(patch_text):
            path = op["path"]
            if op["action"] == "add":
                self._bump(path, "\n".join(op["lines"]) + ("\n" if op["lines"] else ""),
                           "rewrite" if path in self.files else "create")
            elif op["action"] == "update":
                # Without the file's in-session base (e.g. a pre-existing repo file) a
                # context diff cannot be reconstructed; report it instead of fabricating.
                if path not in self.files:
                    self.failures += 1
                    continue
                new, ok = _apply_update(self.files[path]["content"], op["hunk"])
                if not ok:
                    self.failures += 1
                    continue
                self._bump(path, new, "update")
            elif op["action"] == "delete" and path in self.files:
                self._bump(path, "", "delete")

    def artifacts(self) -> List[Dict[str, Any]]:
        return [self.files[p] for p in self.order]


def reconstruct(patch_texts: List[str]) -> Tuple[List[Dict[str, Any]], int]:
    """Apply patch blocks in order. Returns (artifacts, unmatched-hunk count)."""
    r = _Reconstructor()
    for text in patch_texts:
        r.feed(text)
    return r.artifacts(), r.failures
