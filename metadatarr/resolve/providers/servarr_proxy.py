"""Servarr-metadata-proxy provider via metadatarr's own HTTP clients.

Hits the public proxies that Sonarr / Radarr / Lidarr query for their own
metadata — no self-hosting, no API keys:

- ``skyhook.sonarr.tv/v1``     → TVDB-shaped series metadata
- ``radarrapi.servarr.com/v1`` → TMDB-shaped movie metadata
- ``api.lidarr.audio/v0.4``    → MusicBrainz-shaped artist metadata
- ``openlibrary.org``          → book / author / edition metadata

This is the "no-Arr-stack-needed" sibling of the ``arr_*`` providers: those
require the user to run their own Sonarr / Radarr / Lidarr; this one is
always available because it's bundled with metadatarr.
"""
from __future__ import annotations

import logging
from typing import Optional

from metadatarr.client import ArrMetadataClient, OpenLibraryClient
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityKind, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType
from mediavocab.models.signals import Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.servarr_proxy")


class ServarrProxyProvider(MetadataProvider):
    """Single provider that dispatches to skyhook / radarr / lidarr / OpenLibrary by medium."""

    name = "metadatarr"
    media = {MediaType.MOVIE, MediaType.TV, MediaType.MUSIC, MediaType.BOOK}

    def __init__(self) -> None:
        self._client = ArrMetadataClient()
        self._ol = OpenLibraryClient()

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        try:
            if signals.medium == MediaType.MOVIE:
                return self._lookup_movie(signals)
            if signals.medium == MediaType.TV:
                return self._lookup_tv(signals)
            if signals.medium == MediaType.MUSIC and signals.artist:
                return self._lookup_artist(signals)
            if signals.medium == MediaType.BOOK:
                return self._lookup_book(signals)
            if signals.medium is not None:
                return None
            for kind_lookup in (self._lookup_movie, self._lookup_tv):
                got = kind_lookup(signals)
                if got is not None:
                    return got
            return None
        except Exception as exc:
            LOG.warning("metadatarr-servarr-proxy lookup failed: %s", exc)
            return None

    def _lookup_movie(self, signals: Signals) -> Optional[ProviderMatch]:
        results = self._client.search_movie(signals.title)
        if not results:
            return None
        top = results[0]
        cand = Signals(title=top.title, year=top.year, medium=MediaType.MOVIE)
        return ProviderMatch(
            provider=self.name,
            confidence=0.85 * match_quality(signals, cand),
            signals=cand,
            external_ids=ExternalIds(
                tmdb_movie=int(top.tmdb_id) if top.tmdb_id else None,
            ),
        )

    def _lookup_tv(self, signals: Signals) -> Optional[ProviderMatch]:
        results = self._client.search_series(signals.title)
        if not results:
            return None
        top = results[0]
        cand = Signals(title=top.title, year=top.year, medium=MediaType.TV)
        return ProviderMatch(
            provider=self.name,
            confidence=0.85 * match_quality(signals, cand),
            signals=cand,
            external_ids=ExternalIds(
                tvdb=int(top.tvdb_id) if top.tvdb_id else None,
            ),
        )

    def _lookup_book(self, signals: Signals) -> Optional[ProviderMatch]:
        query = signals.title
        if signals.artist:
            query = f"{signals.title} {signals.artist}"
        results = self._ol.search(query, limit=5)
        if not results:
            return None
        top = results[0]

        external = ExternalIds(olid=top.work_id)
        for raw_isbn in top.isbn or []:
            digits = raw_isbn.replace("-", "").replace(" ", "")
            if len(digits) == 13 and external.isbn_13 is None:
                external.isbn_13 = digits
            elif len(digits) == 10 and external.isbn_10 is None:
                external.isbn_10 = digits
            if external.isbn_10 and external.isbn_13:
                break

        relations: dict = {}
        if top.author_names:
            entries = []
            for name, key in zip(top.author_names,
                                 (top.author_keys + [None] * len(top.author_names))):
                ext = ExternalIds()
                if key:
                    ext.extra["openlibrary_author"] = key
                entries.append(ProviderEntity(
                    kind=EntityKind.AUTHOR, name=name, external_ids=ext,
                ))
            relations[EntityKind.AUTHOR] = entries

        language = (top.language[0] if top.language else None) or signals.language

        cand = Signals(
            title=top.title,
            year=top.first_publish_year,
            language=language,
            medium=MediaType.BOOK,
        )
        return ProviderMatch(
            provider=self.name,
            confidence=0.85 * match_quality(signals, cand),
            signals=cand,
            external_ids=external,
            relations=relations,
        )

    def _lookup_artist(self, signals: Signals) -> Optional[ProviderMatch]:
        results = self._client.search_artist(signals.artist)
        if not results:
            return None
        top = results[0]
        relations: dict = {EntityKind.ARTIST: [ProviderEntity(
            kind=EntityKind.ARTIST,
            name=top.name,
            external_ids=ExternalIds(musicbrainz_artist=top.id),
        )]}
        cand = Signals(title=top.name, artist=top.name, medium=MediaType.MUSIC)
        return ProviderMatch(
            provider=self.name,
            confidence=0.75 * match_quality(signals, cand),
            signals=cand,
            external_ids=ExternalIds(musicbrainz_artist=top.id),
            relations=relations,
        )


    # ------------------------------------------------------------------
    # ID-keyed enrichment — ISBN / OLID via OpenLibrary
    # ------------------------------------------------------------------

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Resolve OpenLibrary records keyed by ISBN or OLID.

        Triggers:

        - ``isbn_13`` (or ``isbn_10`` if ``isbn_13`` is missing) →
          :meth:`OpenLibraryClient.get_edition_by_isbn` → emits ``olid``
          (work key when present) + populates the sibling ISBN form.
        - ``olid`` → :meth:`OpenLibraryClient.get_work` → emits no new
          ID slots today but confirms the OLID resolves.

        Note: ``ExternalIds`` already back-fills ISBN-10 ↔ ISBN-13 on
        construction, so callers don't need to provide both forms.
        """
        out = ExternalIds()
        isbn = external_ids.isbn_13 or external_ids.isbn_10
        if isbn:
            try:
                edition = self._ol.get_edition_by_isbn(isbn)
            except Exception:
                edition = None
            if edition is not None:
                # Edition.work_keys[0] is the OLID work id.
                if edition.work_keys and not external_ids.olid:
                    out.olid = edition.work_keys[0]
                if edition.isbn_10 and not external_ids.isbn_10:
                    out.isbn_10 = edition.isbn_10[0]
                if edition.isbn_13 and not external_ids.isbn_13:
                    out.isbn_13 = edition.isbn_13[0]

        if external_ids.olid and out == ExternalIds():
            try:
                work = self._ol.get_work(external_ids.olid)
            except Exception:
                work = None
            if work is None:
                return None
            # Work look-up succeeded — no new IDs to add, but signal that
            # the OLID is live by returning a non-None empty result.
            return ExternalIds()

        if out == ExternalIds():
            return None
        return out


register(ServarrProxyProvider())
