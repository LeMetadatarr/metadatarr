"""pyfanedit provider — fanedit.org / IFDB variant lookup.

Variant-only: does not participate in primary resolution (lookup returns None).
Triggered only when ``signals.include_variants=True`` and ``medium==MOVIE``.

Uses ``search_by_original_title()`` which filters by the ``original_title``
field so results are confined to fanedits of the requested film, not anything
that merely mentions the title in the fanedit's own name. A search that fails
raises, so the fan-out records it in ``provider_errors`` rather than reading it
as a film without fan edits.

Each edit carries what IFDB's search listing gives: the faneditor, the edit's
running time and release date, its cover and its synopsis. The formats an
edit is available in and how it is released are copied when the search result
carries them; IFDB shows them on an edit's own page, which is not read.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional

from pyfanedit import FaneditClient

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType, VariantKind, PlaybackType
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.pyfanedit")

# Map upstream pyfanedit kinds to (mediavocab VariantKind, fanedit_subtype).
# Sub-types intentionally absent from the foundation VariantKind enum
# (fanfix, fanmix, fanedit_short) live in the free-text subtype slot.
_FANEDIT_TYPE_MAP: dict = {
    "fanfix":        (VariantKind.FANEDIT,     "fanfix"),
    "fanmix":        (VariantKind.FANEDIT,     "fanmix"),
    "extended":      (VariantKind.EXTENDED,    None),
    "tv_to_movie":   (VariantKind.TV_TO_MOVIE, None),
    "movie_to_tv":   (VariantKind.MOVIE_TO_TV, None),
    "shorts":        (VariantKind.FANEDIT,     "fanedit_short"),
    "special":       (VariantKind.FANEDIT,     None),
    "preservation":  (VariantKind.PRESERVATION, None),
    "documentary":   (VariantKind.OTHER,       None),
}

# IFDB fields copied onto a variant under these names, when the library has them.
_FIELDS = (("faneditor", "faneditor"), ("running_time", "running_time"), ("release_date", "fanedit_release_date"),
           ("cover_url", "cover_url"), ("synopsis", "synopsis"), ("available_in", "available_in"),
           ("release_information", "release_information"))

_SEPARATOR = re.compile(r"^[\s:\-\u2013\u2014|/]+")
_BOUNDARY = re.compile(r"^[\s:\-\u2013\u2014|/(]")


def edit_name(title: str, original_title: Optional[str]) -> str:
    """The edit's own name: its IFDB title after the film's title ("Alien: FanFix"
    for "Alien" is "FanFix"), or the whole title when it does not begin with it
    or the film's title runs on into the next word ("Aliens: Special")."""
    title = (title or "").strip()
    folded = unicodedata.normalize("NFC", title)
    base = unicodedata.normalize("NFC", (original_title or "").strip())
    if base and folded.lower().startswith(base.lower()):
        tail = folded[len(base):]
        if _BOUNDARY.match(tail):
            rest = _SEPARATOR.sub("", tail).strip()
            if rest:
                return rest
    return title


def variant_extra(summary: Any) -> Dict[str, Any]:
    """The variant fields of an IFDB search result."""
    vk, subtype = _FANEDIT_TYPE_MAP.get((summary.fanedit_type or "").lower(), (VariantKind.OTHER, None))
    extra: Dict[str, Any] = {"fanedit_variant_kind": vk.value,
                             "edit_name": edit_name(summary.title, getattr(summary, "original_title", None))}
    if subtype:
        extra["fanedit_subtype"] = subtype
    if summary.url:
        extra["fanedit_url"] = summary.url
    if summary.fanedit_type:
        extra["fanedit_type"] = summary.fanedit_type
    for attr, key in _FIELDS:
        value = getattr(summary, attr, None)
        if isinstance(value, str):
            value = value.strip()
        if value:
            extra[key] = value
    return extra


class PyfaneditProvider(MetadataProvider):
    name = "pyfanedit"
    media = {MediaType.MOVIE}
    playback_type = {PlaybackType.VIDEO}

    def __init__(self) -> None:
        try:
            self._client = FaneditClient()
            self._available = True
        except Exception as exc:
            LOG.warning("pyfanedit init failed: %s", exc)
            self._client = None
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None

    def search_title(self, title: str) -> list:
        """IFDB's fan edits of the work titled ``title``; raises when fanedit.org cannot be read."""
        if not self._available:
            raise RuntimeError("pyfanedit is not available")
        return list(self._client.search_by_original_title(title))

    def list_variants(self, external_ids: ExternalIds,
                      signals: Optional[Signals] = None) -> List[ProviderEntity]:
        if not self._available:
            return []
        imdb = external_ids.imdb
        title = (signals.title if signals else None) or (external_ids.extra or {}).get("_search_title")
        if not title:
            return []
        from metadatarr.catalog.sources.pyfanedit import YEAR_TOLERANCE, release_date
        from metadatarr.catalog.shapes import year_of

        year = signals.year if signals else None
        out = []
        for summary in self.search_title(title):
            extra = variant_extra(summary)
            made = year_of(release_date(extra.get("fanedit_release_date")))
            if year and made and made < year - YEAR_TOLERANCE:
                continue
            out.append(ProviderEntity(
                role=EntityRole.OTHER,
                name=summary.title,
                image_url=summary.cover_url or None,
                external_ids=ExternalIds(
                    fanedit_id=summary.fanedit_id,
                    derived_from_imdb=imdb,
                    extra=extra,
                ),
            ))
        return out


register(PyfaneditProvider())
