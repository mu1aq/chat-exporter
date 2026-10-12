"""Provider router for the single shared-chat-export command.

The router classifies a share URL and imports the matching provider adapter
before handing control to the common CLI. Keeping URL classification in one
small, testable module lets the CLI keep its batch/file/stdin support.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Route:
    provider: str
    module: str
    canonical_url: str
    share_id: str


def _clean(value: str) -> str:
    return str(value or "").strip().strip("<>\"'")


def detect_provider(value: str) -> Optional[str]:
    """Return "chatgpt" or "claude" for an exact public-share host, else None."""
    raw = _clean(value)
    if not raw:
        return None
    candidate = raw if "://" in raw else "https://" + raw
    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme.lower() != "https":
        return None
    if host == "chatgpt.com" and parsed.path.startswith("/share/"):
        return "chatgpt"
    if host in {"claude.ai", "www.claude.ai"} and (
        parsed.path.startswith("/share/") or parsed.path.startswith("/api/chat_snapshots/")
    ):
        return "claude"
    return None


def route_url(value: str) -> Route:
    """Validate a link with its provider module and return its canonical route."""
    provider = detect_provider(value)
    if provider == "chatgpt":
        adapter = importlib.import_module("shared_chat_exporter.chatgpt")
        canonical = adapter.validate_chatgpt_url(_clean(value))
        return Route(provider, adapter.__name__, canonical, adapter.chatgpt_share_id(canonical))
    if provider == "claude":
        adapter = importlib.import_module("shared_chat_exporter.snapshot")
        share_id = adapter.share_id_from(_clean(value))
        return Route(provider, adapter.__name__, adapter.share_page_url(share_id), share_id)
    raise ValueError(
        "Not a supported public share link. "
        "Pass a https://chatgpt.com/share/... or https://claude.ai/share/... link."
    )


def routes_from_args(argv: Sequence[str]) -> List[Route]:
    """Route every share-link argument, leaving option values and files alone."""
    routes: List[Route] = []
    for value in argv:
        if detect_provider(value):
            routes.append(route_url(value))
    return routes


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--detect"]:
        if len(args) != 2:
            print("usage: shared-chat-export --detect <share link>", file=sys.stderr)
            return 2
        try:
            route = route_url(args[1])
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(route.provider)
        return 0

    # Validate share links and import the matching provider dependency up front.
    # File, stdin and legacy Claude share-id inputs stay supported by the CLI.
    try:
        routes_from_args(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    from .cli import main as core_main

    return core_main(args)


__all__ = ["Route", "detect_provider", "route_url", "routes_from_args", "main"]
