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
from metadatarr.resolve.entities import EntityKind, ProviderEntity
from metadatarr.resolve.external_ids import ExternalIds
from metadatarr.resolve.signals import Medium, Signals, VariantKind

LOG = logging.getLogger("metadatarr.resolve.providers.pyfanedit")

_FANEDIT_TYPE_MAP = {
    "fanfix":    VariantKind.FANEDIT,
    "fanmix":    VariantKind.FANEDIT,
    "extended":  VariantKind.EXTENDED,
}


class PyfaneditProvider(MetadataProvider):
    name = "pyfanedit"
    media = {Medium.MOVIE}

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
            vk = _FANEDIT_TYPE_MAP.get(
                (summary.fanedit_type or "").lower(), VariantKind.OTHER
            )
            extra: dict = {"fanedit_variant_kind": vk.value}
            if summary.url:
                extra["fanedit_url"] = summary.url
            if summary.fanedit_type:
                extra["fanedit_type"] = summary.fanedit_type
            out.append(ProviderEntity(
                kind=EntityKind.RELEASE,
                name=summary.title,
                external_ids=ExternalIds(
                    fanedit_id=summary.fanedit_id,
                    derived_from_imdb=imdb,
                    extra=extra,
                ),
            ))
        return out


register(PyfaneditProvider())
