"""TMDB (The Movie Database) provider — requires ``TMDB_API_KEY`` env var.

Keys written to :attr:`ExternalIds.tmdb_movie` (integer TMDB movie id).

Genre-gating is intentionally left empty so the provider responds to any
``MediaType.MOVIE`` query regardless of genre tags.

The HTTP call, response parsing, and the title/year confidence heuristic all
live in :class:`pytmdb.TMDBClient` (``best_match``); this provider only adapts
its result into a :class:`ProviderMatch`.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from unblock_requests import CloudflareSession
from pytmdb import TMDBClient

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab.models import ExternalIds
from mediavocab import MediaType, PlaybackType
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.tmdb")

_session: Optional[CloudflareSession] = None


def _http() -> CloudflareSession:
    """Shared anti-bot HTTP transport (curl_cffi impersonation by default)."""
    global _session
    if _session is None:
        _session = CloudflareSession()
    return _session


class TMDBProvider(MetadataProvider):
    name = "tmdb"
    media = {MediaType.MOVIE}
    playback_type = {PlaybackType.VIDEO}

    def is_available(self) -> bool:
        return bool(os.environ.get("TMDB_API_KEY", ""))

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        key = os.environ.get("TMDB_API_KEY", "")
        if not key:
            return None

        client = TMDBClient(api_key=key)
        # Route the client through this provider's shared anti-bot transport
        # (also the seam the offline cassette tests patch).
        client._session = _http()

        try:
            match = client.best_match(signals.title, signals.year)
        except Exception as exc:
            LOG.warning("TMDB search failed: %s", exc)
            return None

        if match is None:
            return None
        movie, confidence = match

        return ProviderMatch(
            provider=self.name,
            confidence=confidence,
            external_ids=ExternalIds(tmdb_movie=movie.id),
        )


register(TMDBProvider())
