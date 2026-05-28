"""MyAnimeList (MAL) provider — free, no API key required."""
from __future__ import annotations

import logging
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab.models import ExternalIds
from mediavocab import PlaybackType
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.mal")


class MALProvider(MetadataProvider):
    name = "mal"
    playback_type = {PlaybackType.VIDEO}
    genre_filter = {"anime", "hentai", "animation"}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        try:
            from pymal.search import search_anime
            results = search_anime(signals.title)
        except Exception as exc:
            LOG.debug("MAL search failed: %s", exc)
            return None

        if not results:
            return None

        query = signals.title.lower()
        best_card = None
        best_confidence = -1.0

        for card in results:
            title_lower = card.title.lower()
            if title_lower == query:
                confidence = 0.95
            elif query in title_lower or title_lower in query:
                confidence = 0.70
            else:
                confidence = 0.40
            if confidence > best_confidence:
                best_confidence = confidence
                best_card = card

        if best_card is None:
            best_card = results[0]
            best_confidence = 0.40

        return ProviderMatch(
            provider=self.name,
            confidence=best_confidence,
            external_ids=ExternalIds(extra={
                "mal_id": best_card.mal_id,
                "mal_url": best_card.url,
            }),
        )


register(MALProvider())
