"""턴 고르기: 번호 범위, 마지막 N개, 정규식 검색."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Optional, Set


class SelectError(ValueError):
    pass


def parse_turn_spec(spec: str, total: int) -> Set[int]:
    """'1-3,5,8-' 같은 표기를 턴 번호 집합으로 바꿉니다. '-3'은 1~3, '8-'은 8~끝."""
    picked: Set[int] = set()
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)-(\d*)|(\d+)", part)
        if not m or part == "-":
            raise SelectError(f"턴 범위를 읽을 수 없습니다: '{part}' (예: 1-3,5,8-)")
        if m.group(3):
            picked.add(int(m.group(3)))
        else:
            lo = int(m.group(1)) if m.group(1) else 1
            hi = int(m.group(2)) if m.group(2) else total
            if lo > hi and m.group(2):
                raise SelectError(f"턴 범위가 거꾸로입니다: '{part}'")
            picked.update(range(lo, hi + 1))
    return picked


def select_turns(conv: Dict[str, Any], turns: Optional[str] = None, last: Optional[int] = None,
                 grep: Optional[str] = None) -> Dict[str, Any]:
    """조건에 맞는 턴만 남긴 사본을 돌려줍니다. 턴 번호는 원래 번호를 유지합니다."""
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
            raise SelectError(f"검색 패턴이 올바르지 않습니다: {e}") from e
        items = [t for t in items if rx.search(t["user_input"]) or rx.search(t["agent_output"])
                 or rx.search(t.get("thinking") or "")]
    out = copy.copy(conv)
    out["turns"] = items
    return out
