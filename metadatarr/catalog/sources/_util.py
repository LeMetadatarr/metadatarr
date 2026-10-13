# SPDX-License-Identifier: Apache-2.0
"""Small helpers shared by the catalogue sources."""
from __future__ import annotations

import html
import re
from typing import Any, Iterable, Optional

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<\s*(br|/p)\s*/?>", re.IGNORECASE)


def plain_text(text: Optional[str], limit: int = 4000) -> str:
    """Text with HTML tags removed and entities decoded, cut at ``limit`` characters."""
    if not text:
        return ""
    out = _BREAK.sub("\n", str(text))
    out = html.unescape(_TAG.sub("", out))
    out = "\n".join(line.strip() for line in out.splitlines())
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out[:limit]


def image(images: Optional[Iterable[dict]], *types: str, key: str = "Url", type_key: str = "CoverType") -> str:
    """The URL of the first image whose type is one of ``types`` (in that order of preference)."""
    images = [i for i in (images or ()) if isinstance(i, dict)]
    for wanted in types:
        for i in images:
            if str(i.get(type_key) or "").lower() == wanted.lower() and i.get(key):
                return str(i[key])
    return ""


def as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def minutes(value: Any, unit: float = 1.0) -> Optional[float]:
    """``value`` (in units of ``unit`` minutes) as minutes, or None when absent or not positive."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number * unit, 2) if number > 0 else None


def ids(**pairs: Any) -> dict:
    """``{scheme: str(value)}`` for the pairs whose value is set."""
    return {k: str(v) for k, v in pairs.items() if v not in (None, "", 0)}
