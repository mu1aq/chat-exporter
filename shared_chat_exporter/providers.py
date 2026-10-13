"""Provider adapters: one place that maps a provider name to how its loaded
data becomes a normalized conversation and what its raw file is called.

The CLI acquires input (HTTP, browser, file, stdin) and tags each item with a
provider name; everything downstream (normalization, bundling) goes through the
registry here, so adding a provider is one entry instead of edits scattered
across the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Protocol

from .chatgpt import extract_chatgpt
from .chatgpt_export import finalize_export
from .extract import Options, extract
from .sessions import CLAUDE_CODE, CODEX, finalize_session

CHATGPT_EXPORT = "chatgpt-export"


class ProviderAdapter(Protocol):
    name: str
    raw_name: str  # filename for the verbatim source inside a bundle

    def normalize(self, loaded: Any, options: Options) -> Dict[str, Any]:
        """Turn a loaded item (``loaded.data`` + ``loaded.item``) into a conversation dict."""
        ...


@dataclass(frozen=True)
class _Adapter:
    name: str
    raw_name: str
    _normalize: Callable[[Any, Options], Dict[str, Any]]

    def normalize(self, loaded: Any, options: Options) -> Dict[str, Any]:
        return self._normalize(loaded, options)


def _claude(ld: Any, opts: Options) -> Dict[str, Any]:
    return extract(ld.data, opts)


def _chatgpt(ld: Any, opts: Options) -> Dict[str, Any]:
    return extract_chatgpt(ld.data)


def _session(ld: Any, opts: Options) -> Dict[str, Any]:
    return finalize_session(extract(ld.data, opts), ld.item.path, ld.data)


def _chatgpt_export(ld: Any, opts: Options) -> Dict[str, Any]:
    return finalize_export(extract(ld.data, opts), ld.item.path)


REGISTRY: Dict[str, _Adapter] = {
    a.name: a for a in (
        _Adapter("claude", "raw.json", _claude),
        _Adapter("chatgpt", "capture.json", _chatgpt),
        _Adapter(CLAUDE_CODE, "raw.jsonl", _session),
        _Adapter(CODEX, "raw.jsonl", _session),
        _Adapter(CHATGPT_EXPORT, "conversation.json", _chatgpt_export),
    )
}


def get_adapter(provider: str) -> _Adapter:
    """Adapter for ``provider``, falling back to the Claude snapshot adapter."""
    return REGISTRY.get(provider, REGISTRY["claude"])
