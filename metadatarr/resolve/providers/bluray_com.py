"""blu-ray.com metadata provider (HTML scraper, no API key required).

Covers physical Blu-ray and 4K UHD disc releases with regional editions,
technical specs (codec, bitrate, HDR), audio tracks, and slipcover data.

Keys written to :attr:`ExternalIds.extra`:

- ``bluray_com_url``  — canonical page URL
- ``bluray_com_cover`` — cover image URL
"""
from __future__ import annotations

import logging
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab.models import ExternalIds
from mediavocab import MediaType
from mediavocab.models.signals import Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.bluray_com")


class BlurayComProvider(MetadataProvider):
    name = "bluray_com"
    media = {MediaType.MOVIE, MediaType.TV}

    def __init__(self) -> None:
        from metadatarr.client import BlurayComClient
        self._client = BlurayComClient()

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None

        try:
            hits = self._client.search(signals.title)
        except Exception as exc:
            LOG.warning("blu-ray.com search failed: %s", exc)
            return None

        if not hits:
            return None

        # Filter by year if provided
        if signals.year is not None:
            year_hits = [h for h in hits if h.year and abs(h.year - signals.year) <= 1]
            if year_hits:
                hits = year_hits

        top = hits[0]
        cand_signals = Signals(
            title=top.title,
            year=top.year,
            medium=signals.medium or MediaType.MOVIE,
            source_format="Blu-ray",
        )
        quality = match_quality(signals, cand_signals)

        extra: dict = {}
        if top.url:
            extra["bluray_com_url"] = top.url
        if top.cover_url:
            extra["bluray_com_cover"] = top.cover_url

        return ProviderMatch(
            provider=self.name,
            confidence=0.65 * quality,
            signals=cand_signals,
            external_ids=ExternalIds(
                bluray_com_id=top.bluray_com_id,
                extra=extra,
            ),
        )


register(BlurayComProvider())
