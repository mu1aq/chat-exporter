"""Keep fetched snapshot bytes on disk so they are not downloaded again."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from .snapshot import SnapshotError, parse_snapshot_text, read_text_file


def default_cache_dir() -> Path:
    env = os.environ.get("CSE_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "claude-share-extract" / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "claude-share-extract"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "claude-share-extract"


class SnapshotCache:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else default_cache_dir()
        self.dir = self.root / "snapshots"

    def path_for(self, share_id: str) -> Path:
        safe = "".join(ch for ch in share_id if ch.isalnum() or ch == "-")
        return self.dir / f"{safe}.json"

    def get(self, share_id: str) -> Optional[str]:
        p = self.path_for(share_id)
        if not p.is_file():
            return None
        try:
            text = read_text_file(p)
            parse_snapshot_text(text)
            return text
        except (OSError, SnapshotError):
            return None

    def put(self, share_id: str, text: str) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.path_for(share_id)
        fd, tmp = tempfile.mkstemp(dir=str(self.dir), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, p)
        return p

    def entries(self) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        if not self.dir.is_dir():
            return out
        for p in sorted(self.dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            title, turns = "", None
            try:
                snap = parse_snapshot_text(read_text_file(p))
                title = snap.get("snapshot_name") or ""
                turns = sum(1 for m in snap["chat_messages"] if isinstance(m, dict) and m.get("sender") == "human")
            except (OSError, SnapshotError):
                title = "(unreadable)"
            st = p.stat()
            out.append({"share_id": p.stem, "title": title, "user_messages": turns, "bytes": st.st_size,
                        "saved_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)), "path": str(p)})
        return out

    def remove(self, share_id: str) -> bool:
        p = self.path_for(share_id)
        if p.is_file():
            p.unlink()
            return True
        return False

    def clear(self) -> int:
        n = 0
        if self.dir.is_dir():
            for p in self.dir.glob("*.json"):
                p.unlink()
                n += 1
        return n
