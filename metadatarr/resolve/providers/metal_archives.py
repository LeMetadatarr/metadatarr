"""Encyclopaedia Metallum metadata provider.

Looks up music rows against ``metal-archives.com`` via :mod:`pymetal`,
returning Metal-Archives ids (band / release / song) and entity relations
(artist, album).

Compatible with ``pymetal >= 1.0.0a1``: uses :class:`pymetal.MetalArchives`
and reads flat ``SongSearchHit`` fields (``band_id``, ``band_name``,
``release_id``, ``release_title``, ``song_id``). Earlier pymetal releases
returned a nested object — we no longer support that shape.

This module imports :mod:`pymetal` lazily; if the optional dependency is
not installed, the provider exists but reports ``is_available() == False``.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityKind, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType
from mediavocab.models.signals import Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.metal_archives")


class MetalArchivesProvider(MetadataProvider):
    name = "metal_archives"
    media = {MediaType.MUSIC}

    def __init__(self) -> None:
        try:
            from pymetal import MetalArchives  # noqa: WPS433
            self._client = MetalArchives()
            self._available = True
        except ImportError:
            self._client = None
            self._available = False
        except Exception as exc:  # pragma: no cover — pymetal init failure
            LOG.warning("pymetal init failed: %s", exc)
            self._client = None
            self._available = False

    def is_available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search(self, signals: Signals) -> List:
        if not (self._available and signals.title and signals.artist):
            return []
        if signals.medium and signals.medium != MediaType.MUSIC:
            return []
        try:
            return list(self._client.search_songs(
                song_title=signals.title, band_name=signals.artist,
            ))
        except Exception as exc:
            LOG.warning("metal-archives song search failed: %s", exc)
            return []

    def _build_match(self, hit, signals: Signals) -> ProviderMatch:
        # SongSearchHit (pymetal>=1.0): flat record, no nested band/release.
        match_signals = Signals(
            title=getattr(hit, "title", None) or signals.title,
            artist=getattr(hit, "band_name", None),
            medium=MediaType.MUSIC,
        )

        external = ExternalIds(
            metal_archives_band=getattr(hit, "band_id", None),
            metal_archives_release=getattr(hit, "release_id", None),
            metal_archives_song=getattr(hit, "song_id", None) or None,
        )

        relations: dict = {}
        if getattr(hit, "band_name", None):
            relations[EntityKind.ARTIST] = [ProviderEntity(
                kind=EntityKind.ARTIST,
                name=hit.band_name,
                external_ids=ExternalIds(metal_archives_band=hit.band_id),
            )]
        if getattr(hit, "release_title", None):
            relations[EntityKind.ALBUM] = [ProviderEntity(
                kind=EntityKind.ALBUM,
                name=hit.release_title,
                external_ids=ExternalIds(metal_archives_release=hit.release_id),
            )]

        return ProviderMatch(
            provider=self.name,
            confidence=0.9 * match_quality(signals, match_signals),
            signals=match_signals,
            external_ids=external,
            relations=relations,
        )

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        hits = self._search(signals)
        if not hits:
            return None
        return self._build_match(hits[0], signals)

    def lookup_candidates(self, signals: Signals) -> List[ProviderMatch]:
        """Up to 5 ranked song hits — same single search call as ``lookup``."""
        out = [self._build_match(h, signals) for h in self._search(signals)[:5]]
        out.sort(key=lambda m: m.confidence, reverse=True)
        return out


    # ------------------------------------------------------------------
    # ID-keyed enrichment — MA band/release ids → external links
    # ------------------------------------------------------------------

    # MA's "external links" section labels external services. Map the
    # well-known ones onto our ExternalIds shape.
    _LINK_NAME_FIRST_CLASS = {
        # exact, case-insensitive matches
        "wikidata": ("wikidata", lambda url: url.rstrip("/").rsplit("/", 1)[-1]),
        "imdb":     ("imdb",     lambda url: url.rstrip("/").rsplit("/", 1)[-1]),
    }
    _LINK_NAME_EXTRA = {
        "bandcamp":          "bandcamp_artist_url",
        "soundcloud":        "soundcloud_artist_url",
        "youtube":           "youtube_channel_url",
        "youtube music":     "youtube_music_artist_url",
        "official website":  "official_site",
        "official site":     "official_site",
        "wikipedia":         "wikipedia_url",
        "discogs":           "discogs_url",
        "allmusic":          "allmusic_url",
        "spotify":           "spotify_url",
        "encyclopaedia metallum": "metal_archives_url",
    }

    @classmethod
    def _absorb_links(cls, links, out: ExternalIds) -> None:
        for link in links or []:
            name = (getattr(link, "name", None) or "").strip().lower()
            url = str(getattr(link, "url", "") or "").strip()
            if not (name and url):
                continue
            if name in cls._LINK_NAME_FIRST_CLASS:
                field, parser = cls._LINK_NAME_FIRST_CLASS[name]
                value = parser(url)
                if value and getattr(out, field, None) in (None, ""):
                    setattr(out, field, value)
            elif name in cls._LINK_NAME_EXTRA:
                out.extra.setdefault(cls._LINK_NAME_EXTRA[name], url)

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Resolve MA band/release records keyed by MA ids.

        Triggers (each is independently optional):

        - ``metal_archives_band`` → ``MetalArchives.get_links(id, "band")``
          → Bandcamp / SoundCloud / Wikipedia / Wikidata / Spotify URLs the
          band lists in its "External links" tab.
        - ``metal_archives_release`` → ``MetalArchives.get_links(id, "album")``
          → release-specific external links (Bandcamp release page etc.).
        """
        if not self._available:
            return None

        out = ExternalIds()
        out.extra = {}
        any_call = False

        if external_ids.metal_archives_band:
            any_call = True
            try:
                links = self._client.get_links(int(external_ids.metal_archives_band),
                                               entity_type="band")
            except Exception as exc:
                LOG.warning("metal-archives band links failed: %s", exc)
                links = None
            self._absorb_links(links, out)

        if external_ids.metal_archives_release:
            any_call = True
            try:
                links = self._client.get_links(int(external_ids.metal_archives_release),
                                               entity_type="album")
            except Exception as exc:
                LOG.warning("metal-archives release links failed: %s", exc)
                links = None
            self._absorb_links(links, out)

        if not any_call or out == ExternalIds(extra={}):
            return None
        return out


register(MetalArchivesProvider())
