"""File and folder naming helpers."""

from __future__ import annotations

import re

_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_NAME_LENGTH = 120


def safe_filename(text: str, fallback: str = "Download") -> str:
    """Make text safe to use as a single file or folder name on any OS."""
    cleaned = _FORBIDDEN.sub("_", text or "").strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:MAX_NAME_LENGTH].rstrip(" .") or fallback
