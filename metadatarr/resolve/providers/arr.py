"""Arr-stack providers (Sonarr / Radarr / Readarr / Lidarr).

Each Arr instance exposes a ``/api/v3/`` REST API with a ``X-Api-Key``
header and a ``GET /lookup`` endpoint. We use those as enrichment
sources — never as a download or push channel.

Configuration is per-instance:

- ``MEDIA_ARCHIVIST_SONARR_URL``  / ``MEDIA_ARCHIVIST_SONARR_KEY``
- ``MEDIA_ARCHIVIST_RADARR_URL``  / ``MEDIA_ARCHIVIST_RADARR_KEY``
- ``MEDIA_ARCHIVIST_READARR_URL`` / ``MEDIA_ARCHIVIST_READARR_KEY``
- ``MEDIA_ARCHIVIST_LIDARR_URL``  / ``MEDIA_ARCHIVIST_LIDARR_KEY``

When either env var is missing, the provider self-disables.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests

from mediavocab import MediaType
from metadatarr.resolve.entities import EntityKind, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import (
    MetadataProvider,
    ProviderMatch,
    register,
)

LOG = logging.getLogger("metadatarr.resolve.providers.arr")


class _ArrBase(MetadataProvider):
    """Shared HTTP wiring for an Arr-style instance."""

    env_url: str
    env_key: str
    lookup_path: str

    def __init__(self) -> None:
        self.url = (os.environ.get(self.env_url) or "").rstrip("/")
        self.key = os.environ.get(self.env_key) or ""

    def is_available(self) -> bool:
        return bool(self.url and self.key)

    def _get(self, path: str, **params) -> Any:
        resp = requests.get(
            f"{self.url}{path}",
            params=params,
            headers={"X-Api-Key": self.key},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def _search(self, term: str) -> List[Dict[str, Any]]:
        try:
            data = self._get(self.lookup_path, term=term)
        except requests.RequestException as e:
            LOG.warning("%s lookup failed: %s", self.name, e)
            return []
        # Arr lookup endpoints return a list directly.
        return data if isinstance(data, list) else (data.get("results") or [])


class SonarrProvider(_ArrBase):
    name = "arr_sonarr"
    media = {MediaType.EPISODIC_SERIES}
    env_url = "MEDIA_ARCHIVIST_SONARR_URL"
    env_key = "MEDIA_ARCHIVIST_SONARR_KEY"
    lookup_path = "/api/v3/series/lookup"

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not (self.is_available() and signals.title):
            return None
        if signals.medium and signals.medium != MediaType.EPISODIC_SERIES:
            return None
        results = self._search(signals.title)
        if not results:
            return None
        top = results[0]
        runtime_min = top.get("runtime")
        return ProviderMatch(
            provider=self.name,
            confidence=0.9,
            signals=Signals(
                title=top.get("title"),
                year=top.get("year"),
                country=top.get("originCountry"),
                runtime=runtime_min * 60.0 if runtime_min else None,
                medium=MediaType.EPISODIC_SERIES,
                language=(top.get("originalLanguage") or {}).get("name"),
            ),
            external_ids=ExternalIds(
                tvdb=top.get("tvdbId"),
                imdb=top.get("imdbId"),
                tmdb_tv=top.get("tmdbId"),
            ),
        )


class RadarrProvider(_ArrBase):
    name = "arr_radarr"
    media = {MediaType.MOVIE}
    env_url = "MEDIA_ARCHIVIST_RADARR_URL"
    env_key = "MEDIA_ARCHIVIST_RADARR_KEY"
    lookup_path = "/api/v3/movie/lookup"

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not (self.is_available() and signals.title):
            return None
        if signals.medium and signals.medium != MediaType.MOVIE:
            return None
        results = self._search(signals.title)
        if not results:
            return None
        top = results[0]
        runtime_min = top.get("runtime")
        return ProviderMatch(
            provider=self.name,
            confidence=0.9,
            signals=Signals(
                title=top.get("title"),
                year=top.get("year"),
                runtime=runtime_min * 60.0 if runtime_min else None,
                medium=MediaType.MOVIE,
                language=(top.get("originalLanguage") or {}).get("name"),
            ),
            external_ids=ExternalIds(
                tmdb_movie=top.get("tmdbId"),
                imdb=top.get("imdbId"),
            ),
        )


class ReadarrProvider(_ArrBase):
    name = "arr_readarr"
    media = {MediaType.BOOK}
    env_url = "MEDIA_ARCHIVIST_READARR_URL"
    env_key = "MEDIA_ARCHIVIST_READARR_KEY"
    lookup_path = "/api/v1/book/lookup"

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not (self.is_available() and signals.title):
            return None
        if signals.medium and signals.medium != MediaType.BOOK:
            return None
        results = self._search(signals.title)
        if not results:
            return None
        top = results[0]
        author = top.get("author") or {}
        relations: dict = {}
        if author.get("authorName"):
            relations[EntityKind.AUTHOR] = [ProviderEntity(
                kind=EntityKind.AUTHOR,
                name=author["authorName"],
                external_ids=ExternalIds(
                    extra={"goodreads_author": str(author.get("foreignAuthorId") or "")},
                ),
            )]
        return ProviderMatch(
            provider=self.name,
            confidence=0.85,
            signals=Signals(
                title=top.get("title"),
                artist=author.get("authorName"),
                medium=MediaType.BOOK,
            ),
            external_ids=ExternalIds(
                isbn_13=top.get("isbn13"),
                goodreads=str(top.get("foreignBookId") or "") or None,
            ),
            relations=relations,
        )


class LidarrProvider(_ArrBase):
    name = "arr_lidarr"
    media = {MediaType.MUSIC}
    env_url = "MEDIA_ARCHIVIST_LIDARR_URL"
    env_key = "MEDIA_ARCHIVIST_LIDARR_KEY"
    lookup_path = "/api/v1/album/lookup"

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not (self.is_available() and signals.title):
            return None
        if signals.medium and signals.medium != MediaType.MUSIC:
            return None
        results = self._search(signals.title)
        if not results:
            return None
        top = results[0]
        artist = top.get("artist") or {}
        relations: dict = {}
        if artist.get("artistName"):
            relations[EntityKind.ARTIST] = [ProviderEntity(
                kind=EntityKind.ARTIST,
                name=artist["artistName"],
                external_ids=ExternalIds(
                    musicbrainz_artist=artist.get("foreignArtistId"),
                ),
            )]
        if top.get("title"):
            relations[EntityKind.ALBUM] = [ProviderEntity(
                kind=EntityKind.ALBUM,
                name=top["title"],
                external_ids=ExternalIds(
                    musicbrainz_release_group=top.get("foreignAlbumId"),
                ),
            )]
        return ProviderMatch(
            provider=self.name,
            confidence=0.85,
            signals=Signals(
                title=top.get("title"),
                artist=artist.get("artistName"),
                medium=MediaType.MUSIC,
            ),
            external_ids=ExternalIds(
                musicbrainz_release_group=top.get("foreignAlbumId"),
                musicbrainz_artist=artist.get("foreignArtistId"),
            ),
            relations=relations,
        )


register(SonarrProvider())
register(RadarrProvider())
register(ReadarrProvider())
register(LidarrProvider())
