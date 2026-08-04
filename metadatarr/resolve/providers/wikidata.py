"""Wikidata provider — free, no key. Q-id + cross-references (IMDb, TMDB,
TVDB, MB) when available.

The two-step search (``wbsearchentities`` → ``wbgetentities``) plus the reverse
``haswbstatement`` lookup all live in :class:`pywikidata.WikidataClient`. This
provider adapts the client's :class:`pywikidata.models.WikidataExternalIds` into
metadatarr's :class:`mediavocab.models.ExternalIds`, re-applying ISBN
normalization (``mediavocab.text.normalize_isbn``) — a step the standalone
client cannot perform because it does not depend on ``mediavocab``. That keeps
resolver output byte-identical to the pre-extraction provider.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from pywikidata import WikidataClient
from pywikidata.models import WikidataExternalIds

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.transport import make_session
from mediavocab.models import ExternalIds
from mediavocab.text import normalize_isbn
from mediavocab import MediaType
from mediavocab.models.signals import Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.wikidata")

# Shared transport. Kept at module scope so it can be reused across lookups and
# patched by the offline cassette tests; injected into each WikidataClient.
_SESSION = make_session()

# Non-ISBN fields copied straight across from the client's model. ISBN fields
# are handled separately so they can be normalized + cross-filled.
_DIRECT_FIELDS = (
    "imdb",
    "tmdb_movie",
    "tmdb_tv",
    "tvdb",
    "musicbrainz_release_group",
    "musicbrainz_artist",
    "musicbrainz_work",
    "olid",
    "goodreads",
)


class WikidataProvider(MetadataProvider):
    name = "wikidata"
    media = {MediaType.MOVIE, MediaType.EPISODIC_SERIES, MediaType.MUSIC, MediaType.BOOK, MediaType.PODCAST}
    # Universal — Wikidata covers every modality through Q-id cross-reference.
    playback_type: set = set()

    def is_available(self) -> bool:
        return True

    def _client(self) -> WikidataClient:
        client = WikidataClient()
        client._session = _SESSION
        return client

    # ------------------------------------------------------------------
    # WikidataExternalIds -> mediavocab ExternalIds (with ISBN normalization)
    # ------------------------------------------------------------------

    @staticmethod
    def _to_external_ids(wc: WikidataExternalIds) -> ExternalIds:
        external = ExternalIds(wikidata=wc.wikidata)
        for field in _DIRECT_FIELDS:
            value = getattr(wc, field, None)
            if value is not None:
                setattr(external, field, value)
        # Re-apply the ISBN normalization the original in-repo provider ran:
        # normalise, then cross-fill ISBN-10/13 via a fresh model validation.
        for field in ("isbn_13", "isbn_10"):
            raw = getattr(wc, field, None)
            if raw in (None, ""):
                continue
            normalised = normalize_isbn(str(raw))
            if normalised:
                merged = ExternalIds.model_validate(
                    {**external.model_dump(exclude_none=True), field: normalised}
                )
                for fname in ("isbn_10", "isbn_13"):
                    v = getattr(merged, fname)
                    if v:
                        setattr(external, fname, v)
        return external

    @staticmethod
    def _probe_from(external_ids: ExternalIds) -> WikidataExternalIds:
        """Project metadatarr's ExternalIds onto the client's model so its
        reverse ``haswbstatement`` lookup can run."""
        return WikidataExternalIds(
            wikidata=external_ids.wikidata,
            imdb=external_ids.imdb,
            tmdb_movie=external_ids.tmdb_movie,
            tmdb_tv=external_ids.tmdb_tv,
            tvdb=external_ids.tvdb,
            musicbrainz_release_group=external_ids.musicbrainz_release_group,
            musicbrainz_artist=external_ids.musicbrainz_artist,
            musicbrainz_work=external_ids.musicbrainz_work,
            olid=external_ids.olid,
            isbn_13=external_ids.isbn_13,
            isbn_10=external_ids.isbn_10,
            goodreads=external_ids.goodreads,
        )

    def _build_match(self, client: WikidataClient, hit, signals: Signals) -> Optional[ProviderMatch]:
        wc = client.get_external_ids(hit.id)
        if wc is None:
            return None
        external = self._to_external_ids(wc)
        label = hit.label or signals.title
        cand_signals = Signals(title=label)
        return ProviderMatch(
            provider=self.name,
            confidence=0.7 * match_quality(signals, cand_signals),
            signals=cand_signals,
            external_ids=external,
        )

    # ------------------------------------------------------------------
    # Reverse lookup — find a Q-id from a known cross-ref ID
    # ------------------------------------------------------------------

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Find this entity's Q-id (if not already given) and return its
        full claims-derived :class:`ExternalIds`."""
        wc = self._client().enrich(self._probe_from(external_ids))
        if wc is None:
            return None
        return self._to_external_ids(wc)

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        client = self._client()
        hits = client.search(signals.title, language=signals.language or "en", limit=5)
        if not hits:
            return None
        return self._build_match(client, hits[0], signals)

    def lookup_candidates(self, signals: Signals) -> List[ProviderMatch]:
        """Fan out across the top-3 search hits.

        Each candidate costs one extra Wikidata entity-fetch, so cap small.
        """
        if not signals.title:
            return []
        client = self._client()
        hits = client.search(signals.title, language=signals.language or "en", limit=5)
        out: List[ProviderMatch] = []
        for hit in hits[:3]:
            m = self._build_match(client, hit, signals)
            if m is not None:
                out.append(m)
        out.sort(key=lambda m: m.confidence, reverse=True)
        return out


register(WikidataProvider())
