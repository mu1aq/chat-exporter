"""Canonical API for the unified Claude and ChatGPT share exporter.

The original :mod:`claude_share_extract` import remains compatible.
"""

from claude_share_extract import *  # noqa: F401,F403
from claude_share_extract.chatgpt import (  # noqa: F401
    ChatGPTBrowserUnavailable,
    ChatGPTError,
    capture_and_extract,
    capture_chatgpt,
    chatgpt_share_id,
    extract_chatgpt,
    validate_chatgpt_url,
)

