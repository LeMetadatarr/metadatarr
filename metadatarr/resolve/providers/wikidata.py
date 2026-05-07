"""Wikidata provider — free, no key. Q-id + cross-references (IMDb, TMDB,
TVDB, MB) when available.

Uses the ``wbsearchentities`` API to find candidate Q-ids by title, then
``wbgetentities`` to read the cross-reference claims.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import requests

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab.models import ExternalIds
from mediavocab.text import normalize_isbn
from mediavocab import MediaType
from mediavocab.models.signals import Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.wikidata")
_API = "https://www.wikidata.org/w/api.php"
_HEADERS = {
    "User-Agent": "metadatarr/0.1 (+https://github.com/TigreGotico/metadatarr)",
    "Accept": "application/json",
}

# Wikidata property → ExternalIds field mapping.
_PROP_MAP = {
    "P345": "imdb",                       # IMDb ID
    "P4947": "tmdb_movie",                # TMDB movie ID
    "P4983": "tmdb_tv",                   # TMDB TV series ID
    "P4835": "tvdb",                      # TVDB series ID
    "P436": "musicbrainz_release_group",  # MB release group ID
    "P434": "musicbrainz_artist",         # MB artist ID
    "P435": "musicbrainz_work",           # MB work ID
    "P648": "olid",                       # Open Library ID
    "P212": "isbn_13",
    "P957": "isbn_10",
    "P2969": "goodreads",
}


class WikidataProvider(MetadataProvider):
    name = "wikidata"
    media = {MediaType.MOVIE, MediaType.EPISODIC_SERIES, MediaType.MUSIC, MediaType.BOOK, MediaType.PODCAST}
    # Universal — Wikidata covers every modality through Q-id cross-reference.
    modality: set = set()

    def is_available(self) -> bool:
        return True

    def _search(self, signals: Signals) -> List[dict]:
        if not signals.title:
            return []
        try:
            data = requests.get(_API, params={
                "action": "wbsearchentities",
                "search": signals.title,
                "language": signals.language or "en",
                "format": "json",
                "limit": 5,
            }, headers=_HEADERS, timeout=20).json()
        except requests.RequestException as e:
            LOG.warning("Wikidata search failed: %s", e)
            return []
        return data.get("search") or []

    def _claims_to_external_ids(self, qid: str) -> Optional[ExternalIds]:
        """Fetch *qid*'s entity, walk its cross-reference claims, return an
        :class:`ExternalIds` carrying every key in ``_PROP_MAP`` that's set.
        """
        if not qid:
            return None
        try:
            entity = requests.get(_API, params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "claims|labels",
                "format": "json",
            }, headers=_HEADERS, timeout=20).json()
        except requests.RequestException as e:
            LOG.warning("Wikidata entity fetch failed: %s", e)
            return None

        claims = (entity.get("entities", {}).get(qid, {}).get("claims") or {})
        external = ExternalIds(wikidata=qid)
        for prop, field in _PROP_MAP.items():
            stmts = claims.get(prop) or []
            if not stmts:
                continue
            try:
                value = stmts[0]["mainsnak"]["datavalue"]["value"]
            except (KeyError, TypeError, IndexError):
                continue
            if field in {"tmdb_movie", "tmdb_tv", "tvdb"}:
                try:
                    setattr(external, field, int(value))
                except (TypeError, ValueError):
                    pass
            elif field in {"isbn_13", "isbn_10"}:
                # Normalise and cross-fill via a fresh model so the validator runs.
                normalised = normalize_isbn(str(value))
                if normalised:
                    merged = ExternalIds.model_validate(
                        {**external.model_dump(exclude_none=True), field: normalised}
                    )
                    for fname in ("isbn_10", "isbn_13"):
                        v = getattr(merged, fname)
                        if v:
                            setattr(external, fname, v)
            else:
                setattr(external, field, str(value))
        return external

    def _build_match(self, hit: dict, signals: Signals) -> Optional[ProviderMatch]:
        qid = hit.get("id")
        external = self._claims_to_external_ids(qid)
        if external is None:
            return None
        label = hit.get("label") or signals.title
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

    @staticmethod
    def _reverse_probe_value(external_ids: ExternalIds) -> Optional[tuple]:
        """First (property, value) pair we can query Wikidata's
        haswbstatement for. Order matters: prefer the most discriminating
        IDs first."""
        # Same precedence as `_PROP_MAP` keys, ordered by ID quality.
        for prop, field in _PROP_MAP.items():
            value = getattr(external_ids, field, None)
            if value not in (None, ""):
                return prop, str(value)
        return None

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Find this entity's Q-id (if not already given) and return its
        full claims-derived :class:`ExternalIds`."""
        qid = external_ids.wikidata
        if qid:
            return self._claims_to_external_ids(qid)

        probe = self._reverse_probe_value(external_ids)
        if probe is None:
            return None
        prop, value = probe
        try:
            data = requests.get(_API, params={
                "action": "query",
                "list": "search",
                "srsearch": f"haswbstatement:{prop}={value}",
                "format": "json",
                "srlimit": 1,
            }, headers=_HEADERS, timeout=20).json()
        except requests.RequestException as e:
            LOG.warning("Wikidata reverse lookup failed: %s", e)
            return None
        hits = (data.get("query") or {}).get("search") or []
        if not hits:
            return None
        qid = hits[0].get("title")
        return self._claims_to_external_ids(qid)

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        hits = self._search(signals)
        if not hits:
            return None
        return self._build_match(hits[0], signals)

    def lookup_candidates(self, signals: Signals) -> List[ProviderMatch]:
        """Fan out across the top-3 search hits.

        Each candidate costs one extra Wikidata entity-fetch, so cap small.
        """
        hits = self._search(signals)
        out: List[ProviderMatch] = []
        for hit in hits[:3]:
            m = self._build_match(hit, signals)
            if m is not None:
                out.append(m)
        out.sort(key=lambda m: m.confidence, reverse=True)
        return out


register(WikidataProvider())
