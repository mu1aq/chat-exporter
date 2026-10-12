"""Turn selection: number ranges, last N turns, regex search."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Optional, Set


class SelectError(ValueError):
    pass


def parse_turn_spec(spec: str, total: int) -> Set[int]:
    """Turn a spec like '1-3,5,8-' into a set of turn numbers. '-3' means 1..3, '8-' means 8..end."""
    picked: Set[int] = set()
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)-(\d*)|(\d+)", part)
        if not m or part == "-":
            raise SelectError(f"Cannot read turn range: '{part}' (e.g. 1-3,5,8-)")
        if m.group(3):
            picked.add(int(m.group(3)))
        else:
            lo = int(m.group(1)) if m.group(1) else 1
            hi = int(m.group(2)) if m.group(2) else total
            if lo > hi and m.group(2):
                raise SelectError(f"Turn range is reversed: '{part}'")
            picked.update(range(lo, hi + 1))
    return picked


def select_turns(conv: Dict[str, Any], turns: Optional[str] = None, last: Optional[int] = None,
                 grep: Optional[str] = None) -> Dict[str, Any]:
    """Return a copy keeping only matching turns. Turn numbers keep their original values."""
    if not turns and not last and not grep:
        return conv
    items = conv["turns"]
    if turns:
        wanted = parse_turn_spec(turns, len(items))
        items = [t for t in items if t["turn"] in wanted]
    if last:
        items = items[-last:]
    if grep:
        try:
            rx = re.compile(grep, re.IGNORECASE)
        except re.error as e:
            raise SelectError(f"Invalid search pattern: {e}") from e
        items = [t for t in items if rx.search(t["user_input"]) or rx.search(t["agent_output"])
                 or rx.search(t.get("thinking") or "")]
    out = copy.copy(conv)
    out["turns"] = items
    return out
