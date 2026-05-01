"""Thin adapter between tutubo's TitleParser and metadatarr Signals types.

tutubo owns the parsing logic and locale files; this module maps its output
to metadatarr-specific types (VariantKind, Signals fields).
"""
from __future__ import annotations

from typing import Optional

from tutubo import parse_title, TitleParseResult
from tutubo.title_parser import CutKind

from metadatarr.resolve.signals import Signals, VariantKind

# Re-export so callers can import from one place
__all__ = ["parse_title", "TitleParseResult", "signals_from_title"]

_CUT_TO_VARIANT: dict[CutKind, VariantKind] = {
    CutKind.THEATRICAL:  VariantKind.THEATRICAL,
    CutKind.DIRECTORS:   VariantKind.DIRECTORS,
    CutKind.EXTENDED:    VariantKind.EXTENDED,
    CutKind.REMASTERED:  VariantKind.REMASTERED,
    CutKind.COLORIZED:   VariantKind.COLORIZED,
    CutKind.UPSCALED:    VariantKind.UPSCALED,
    CutKind.DELUXE:      VariantKind.DELUXE,
    CutKind.REISSUE:     VariantKind.REISSUE,
    CutKind.COMPILATION: VariantKind.COMPILATION,
    CutKind.ANNIVERSARY: VariantKind.OTHER,
    CutKind.CRITERION:   VariantKind.OTHER,
    CutKind.OTHER:       VariantKind.OTHER,
}


def signals_from_title(raw: str, base: Optional[Signals] = None) -> Signals:
    """Parse ``raw`` and return a Signals instance with extracted fields set.

    If ``base`` is provided, parsed values fill in any absent fields on top
    of it (parsed values never override fields already set on ``base``).
    """
    parsed = parse_title(raw)

    variant_kind: Optional[VariantKind] = None
    if parsed.cut_kind is not None:
        variant_kind = _CUT_TO_VARIANT.get(parsed.cut_kind, VariantKind.OTHER)

    overlay = Signals(
        title=parsed.title or None,
        year=parsed.year,
        season=parsed.season,
        episode=parsed.episode,
        variant_kind=variant_kind,
        edition=parsed.edition,
        source_format=parsed.source_format,
        aka=parsed.aka,
    )

    if base is None:
        return overlay

    from metadatarr.resolve.signals import merged
    # base wins on any field it already has set; overlay fills the gaps
    return merged(base, overlay)
