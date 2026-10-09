"""Apple Podcasts provider — podcasts and audio dramas via the iTunes Search API.

No API key, no setup. Uses the public iTunes Search API which is rate-limited
but requires no authentication.
"""
from __future__ import annotations

import logging
from typing import Optional

from mediavocab import MediaType, PlaybackType
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

LOG = logging.getLogger("metadatarr.resolve.providers.podcast_index")

_ITUNES_SEARCH = "https://itunes.apple.com/search"


class ApplePodcastsProvider(MetadataProvider):
    """Apple Podcasts / iTunes Search — podcasts and audio dramas, no key required."""

    name = "apple_podcasts"
    media = {MediaType.PODCAST, MediaType.AUDIO_DRAMA}
    playback_type = {PlaybackType.AUDIO}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium and signals.medium not in {MediaType.PODCAST, MediaType.AUDIO_DRAMA}:
            return None

        if httpx is None:
            LOG.warning("httpx not installed — apple_podcasts provider unavailable")
            return None

        query = signals.title
        if signals.artist:
            query = f"{signals.title} {signals.artist}"

        try:
            resp = httpx.get(
                _ITUNES_SEARCH,
                params={"term": query, "media": "podcast", "limit": 5},
                timeout=10,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            LOG.warning("apple_podcasts lookup failed: %s", exc)
            return None

        results = data.get("results") or []
        if not results:
            return None

        top = results[0]
        collection_id = top.get("collectionId")

        relations: dict = {}
        artist_name = top.get("artistName")
        if artist_name:
            role = EntityRole.HOST if signals.medium != MediaType.AUDIO_DRAMA else EntityRole.VOICE_ACTOR
            relations[role] = [ProviderEntity(role=role, name=artist_name)]

        medium = signals.medium or MediaType.PODCAST

        return ProviderMatch(
            provider=self.name,
            confidence=0.75,
            signals=Signals(
                title=top.get("collectionName") or signals.title,
                medium=medium,
            ),
            external_ids=ExternalIds(
                apple_podcast_id=int(collection_id) if collection_id else None,
            ),
            relations=relations,
        )


register(ApplePodcastsProvider())
