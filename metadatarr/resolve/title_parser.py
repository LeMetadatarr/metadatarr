"""Adapter between mediavocab's title parser and metadatarr ``Signals``.

mediavocab owns the parsing logic, ``VariantKind`` enum, and locale
files; this module overlays parsed fields onto a ``Signals`` bag.
"""
from __future__ import annotations

from typing import Optional

from mediavocab.text import parse_title, TitleParseResult

from mediavocab.models.signals import Signals

# Re-export so callers can import from one place
__all__ = ["parse_title", "TitleParseResult", "signals_from_title"]


def signals_from_title(raw: str, base: Optional[Signals] = None) -> Signals:
    """Parse ``raw`` and return a ``Signals`` instance with extracted fields set.

    If ``base`` is provided, parsed values fill in any absent fields on top
    of it (parsed values never override fields already set on ``base``).
    """
    parsed = parse_title(raw)

    overlay = Signals(
        title=parsed.title or None,
        year=parsed.year,
        season=parsed.season,
        episode=parsed.episode,
        variant_kind=parsed.variant_kind,
        edition=parsed.edition,
        source_format=parsed.source_format,
    )

    if base is None:
        return overlay

    from mediavocab.models.signals import merge_signals as merged
    # base wins on any field it already has set; overlay fills the gaps
    return merged(base, overlay)
