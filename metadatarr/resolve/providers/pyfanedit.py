"""pyfanedit provider — fanedit.org / IFDB variant lookup.

Variant-only: does not participate in primary resolution (lookup returns None).
Triggered only when ``signals.include_variants=True`` and ``medium==MOVIE``.

Uses ``search_by_original_title()`` which filters by the ``original_title``
field so results are confined to fanedits of the requested film, not anything
that merely mentions the title in the fanedit's own name.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from pyfanedit import FaneditClient

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType, VariantKind
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


class PyfaneditProvider(MetadataProvider):
    name = "pyfanedit"
    media = {MediaType.MOVIE}

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

    def list_variants(self, external_ids: ExternalIds,
                      signals: Optional[Signals] = None) -> List[ProviderEntity]:
        if not self._available:
            return []

        summaries = []
        imdb = external_ids.imdb
        title = (signals.title if signals else None) or (external_ids.extra or {}).get("_search_title")

        if title:
            try:
                summaries = self._client.search_by_original_title(title)
            except Exception as e:
                LOG.debug("pyfanedit original_title search failed: %s", e)

        out = []
        for summary in summaries:
            vk, subtype = _FANEDIT_TYPE_MAP.get(
                (summary.fanedit_type or "").lower(), (VariantKind.OTHER, None)
            )
            extra: dict = {"fanedit_variant_kind": vk.value}
            if subtype:
                extra["fanedit_subtype"] = subtype
            if summary.url:
                extra["fanedit_url"] = summary.url
            if summary.fanedit_type:
                extra["fanedit_type"] = summary.fanedit_type
            out.append(ProviderEntity(
        role=EntityRole.RELEASE,
                name=summary.title,
                external_ids=ExternalIds(
                    fanedit_id=summary.fanedit_id,
                    derived_from_imdb=imdb,
                    extra=extra,
                ),
            ))
        return out


register(PyfaneditProvider())
