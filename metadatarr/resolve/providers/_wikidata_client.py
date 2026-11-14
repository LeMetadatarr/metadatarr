# SPDX-License-Identifier: Apache-2.0
"""The slice of the Wikidata action API the Wikidata provider uses: title
search (``wbsearchentities``), the cross-reference claims of one entity
(``wbgetentities``) and the reverse lookup of an entity by a known id
(``haswbstatement``). No key is needed."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from metadatarr.transport import make_session

API = "https://www.wikidata.org/w/api.php"

# Wikidata property to field. The order is the reverse-lookup precedence:
# the most discriminating ids come first.
PROP_MAP = {
    "P345": "imdb",
    "P4947": "tmdb_movie",
    "P4983": "tmdb_tv",
    "P4835": "tvdb",
    "P436": "musicbrainz_release_group",
    "P434": "musicbrainz_artist",
    "P435": "musicbrainz_work",
    "P648": "olid",
    "P212": "isbn_13",
    "P957": "isbn_10",
    "P2969": "goodreads",
}
_INTEGER_FIELDS = frozenset({"tmdb_movie", "tmdb_tv", "tvdb"})


@dataclass
class SearchHit:
    id: str
    label: Optional[str] = None


@dataclass
class WikidataIds:
    """Cross-reference ids read off an entity's claims."""

    wikidata: Optional[str] = None
    imdb: Optional[str] = None
    tmdb_movie: Optional[int] = None
    tmdb_tv: Optional[int] = None
    tvdb: Optional[int] = None
    musicbrainz_release_group: Optional[str] = None
    musicbrainz_artist: Optional[str] = None
    musicbrainz_work: Optional[str] = None
    olid: Optional[str] = None
    isbn_13: Optional[str] = None
    isbn_10: Optional[str] = None
    goodreads: Optional[str] = None


class WikidataClient:
    def __init__(self) -> None:
        self._session = make_session()
        self._session.headers["Accept"] = "application/json"

    def _get(self, **params: Any) -> Optional[dict]:
        """The decoded JSON object, or ``None`` on any transport, status or
        decoding failure."""
        try:
            r = self._session.get(API, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def search(self, title: str, language: str = "en", limit: int = 5) -> List[SearchHit]:
        if not title:
            return []
        data = self._get(action="wbsearchentities", search=title,
                         language=language, format="json", limit=limit)
        hits = (data or {}).get("search")
        if not isinstance(hits, list):
            return []
        return [SearchHit(id=h["id"], label=h.get("label"))
                for h in hits if isinstance(h, dict) and isinstance(h.get("id"), str)]

    def get_external_ids(self, qid: str) -> Optional[WikidataIds]:
        """The mapped ids of *qid*, ``None`` when the request failed. A merged
        item is read from the item it redirects to; its ``wikidata`` stays the
        requested id."""
        if not qid:
            return None
        data = self._get(action="wbgetentities", ids=qid, props="claims|labels", format="json")
        if not data:
            return None
        entities = data.get("entities")
        if not isinstance(entities, dict):
            return None
        entity = entities.get(qid)
        if entity is None:
            target = (data.get("redirects") or {}).get("to") if isinstance(data.get("redirects"), dict) else None
            entity = entities.get(target) if isinstance(target, str) else None
        claims = entity.get("claims") if isinstance(entity, dict) else None
        if not isinstance(claims, dict):
            claims = {}
        ids = WikidataIds(wikidata=qid)
        for prop, field in PROP_MAP.items():
            statements = claims.get(prop)
            if not statements:
                continue
            try:
                value = statements[0]["mainsnak"]["datavalue"]["value"]
            except (KeyError, TypeError, IndexError):
                continue
            if field in _INTEGER_FIELDS:
                try:
                    setattr(ids, field, int(value))
                except (TypeError, ValueError):
                    pass
            else:
                setattr(ids, field, str(value))
        return ids

    @staticmethod
    def _reverse_probe(ids: WikidataIds) -> Optional[Tuple[str, str]]:
        for prop, field in PROP_MAP.items():
            value = getattr(ids, field)
            if value not in (None, ""):
                return prop, str(value)
        return None

    def find_qid(self, ids: WikidataIds) -> Optional[str]:
        probe = self._reverse_probe(ids)
        if probe is None:
            return None
        prop, value = probe
        data = self._get(action="query", list="search",
                         srsearch=f"haswbstatement:{prop}={value}", format="json", srlimit=1)
        query = (data or {}).get("query")
        hits = query.get("search") if isinstance(query, dict) else None
        if not isinstance(hits, list) or not hits or not isinstance(hits[0], dict):
            return None
        return hits[0].get("title")

    def enrich(self, ids: WikidataIds) -> Optional[WikidataIds]:
        """The full ids of the entity *ids* names, found by its Q-id or by the
        first other id that matches."""
        qid = ids.wikidata or self.find_qid(ids)
        return self.get_external_ids(qid) if qid else None
