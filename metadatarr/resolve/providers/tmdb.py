"""TMDB (The Movie Database) provider — requires ``TMDB_API_KEY`` env var.

Keys written to :attr:`ExternalIds.tmdb_movie` (integer TMDB movie id).

Genre-gating is intentionally left empty so the provider responds to any
``MediaType.MOVIE`` query regardless of genre tags.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab.models import ExternalIds
from mediavocab import MediaType, PlaybackType
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.tmdb")
_BASE = "https://api.themoviedb.org/3"


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
        try:
            resp = requests.get(
                f"{_BASE}/search/movie",
                params={"api_key": key, "query": signals.title, "page": 1},
                timeout=20,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except Exception as exc:
            LOG.warning("TMDB search failed: %s", exc)
            return None

        if not results:
            return None

        query = signals.title.lower()
        best = None
        best_confidence = -1.0

        for result in results:
            title = (result.get("title") or "").lower()
            result_year: Optional[int] = None
            release_date = result.get("release_date") or ""
            if release_date and len(release_date) >= 4:
                try:
                    result_year = int(release_date[:4])
                except ValueError:
                    pass

            if title == query:
                if signals.year and result_year and abs(signals.year - result_year) <= 1:
                    confidence = 0.95
                else:
                    confidence = 0.85
            elif query in title or title in query:
                confidence = 0.60
            else:
                confidence = 0.35

            if confidence > best_confidence:
                best_confidence = confidence
                best = result

        if best is None:
            best = results[0]
            best_confidence = 0.35

        return ProviderMatch(
            provider=self.name,
            confidence=best_confidence,
            external_ids=ExternalIds(tmdb_movie=best.get("id")),
        )


register(TMDBProvider())
