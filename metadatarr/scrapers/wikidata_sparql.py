"""Wikidata SPARQL entity sweeper — expanded edition.

Runs ~90 typed SPARQL queries against the Wikidata Query Service covering
people, creative works, taxonomies, organizations, and Spotify IDs across
film, TV, music, anime/manga, games, podcasts, and more (see ``QUERIES``
below for the full registry).

Each query is independently resumable and offset-paginated against WDQS'
``LIMIT``/``OFFSET``, but a short page ends *that query* (not the whole
harvest) and moves on to the next one in the registry — a shape that doesn't
fit the engine's single offset/skip walk, so :meth:`fetch` is overridden
directly. The cursor is ``{"qidx": i, "offset": o}``, walking ``self.queries``
(all of ``QUERIES``, or just one via ``--query``).

Run it::

    python -m metadatarr.scrapers wikidata_sparql [--output DIR] [--limit N] [--delay SECS]
                                                   [--query NAME] [--list-queries]

Environment:
    WD_CHUNK   Override rows per SPARQL page (default: 5000)
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

SPARQL_URL = "https://query.wikidata.org/sparql"
CHUNK = int(os.environ.get("WD_CHUNK", "5000"))
PEOPLE_CHUNK = 1000  # smaller pages for expensive person queries


# ---------------------------------------------------------------------------
# SPARQL helpers
# ---------------------------------------------------------------------------

def _v(b: Dict, key: str) -> Optional[str]:
    e = b.get(key) or {}
    return e.get("value") or None


def _qid(b: Dict, key: str) -> Optional[str]:
    v = _v(b, key)
    if v and "/Q" in v:
        return "Q" + v.split("/Q")[-1]
    return v


def _year(b: Dict, key: str) -> Optional[int]:
    v = _v(b, key)
    if v:
        try:
            return int(v[:4])
        except ValueError:
            pass
    return None


def _minutes(b: Dict, key: str) -> Optional[int]:
    v = _v(b, key)
    if v:
        try:
            return int(float(v))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Query spec container
# ---------------------------------------------------------------------------

class QuerySpec(NamedTuple):
    name: str
    entity_type: str
    build_sparql: Callable[[int], str]
    parse_binding: Callable[[Dict[str, Any]], Dict[str, Any]]
    chunk: int = CHUNK


# ---------------------------------------------------------------------------
# PEOPLE queries
# ---------------------------------------------------------------------------

def _people_sparql(occupation_qids: List[str], extra_props: str, offset: int) -> str:
    occ_values = " ".join(f"wd:{q}" for q in occupation_qids)
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?birthDate ?deathDate ?gender ?genderLabel ?country ?countryLabel
  ?imdb ?mbid ?website
WHERE {{
  VALUES ?occ {{ {occ_values} }}
  ?item wdt:P31 wd:Q5 ; wdt:P106 ?occ .
  OPTIONAL {{ ?item wdt:P569 ?birthDate }}
  OPTIONAL {{ ?item wdt:P570 ?deathDate }}
  OPTIONAL {{ ?item wdt:P21 ?gender }}
  OPTIONAL {{ ?item wdt:P27 ?country }}
  OPTIONAL {{ ?item wdt:P345 ?imdb }}
  OPTIONAL {{ ?item wdt:P434 ?mbid }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  {extra_props}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {PEOPLE_CHUNK}
OFFSET {offset}
"""


def _parse_person(entity_type: str, extra_fields: Optional[Callable] = None):
    def _parse(b: Dict[str, Any]) -> Dict[str, Any]:
        row = {
            "wikidata_id": _qid(b, "item"),
            "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "birth_year": _year(b, "birthDate"),
            "death_year": _year(b, "deathDate"),
            "gender": _v(b, "genderLabel"),
            "nationality": _v(b, "countryLabel"),
            "nationality_qid": _qid(b, "country"),
            "imdb_id": _v(b, "imdb"),
            "mb_artist_id": _v(b, "mbid"),
            "website": _v(b, "website"),
            "entity_type": entity_type,
        }
        if extra_fields:
            row.update(extra_fields(b))
        return row
    return _parse


def _music_people_sparql(occupation_qids: List[str], offset: int) -> str:
    occ_values = " ".join(f"wd:{q}" for q in occupation_qids)
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?birthDate ?deathDate ?gender ?genderLabel ?country ?countryLabel
  ?imdb ?mbid ?website ?genre ?genreLabel
WHERE {{
  VALUES ?occ {{ {occ_values} }}
  ?item wdt:P31 wd:Q5 ; wdt:P106 ?occ .
  OPTIONAL {{ ?item wdt:P569 ?birthDate }}
  OPTIONAL {{ ?item wdt:P570 ?deathDate }}
  OPTIONAL {{ ?item wdt:P21 ?gender }}
  OPTIONAL {{ ?item wdt:P27 ?country }}
  OPTIONAL {{ ?item wdt:P345 ?imdb }}
  OPTIONAL {{ ?item wdt:P434 ?mbid }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {PEOPLE_CHUNK}
OFFSET {offset}
"""


def _parse_music_person(entity_type: str):
    def _parse(b: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "wikidata_id": _qid(b, "item"),
            "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "birth_year": _year(b, "birthDate"),
            "death_year": _year(b, "deathDate"),
            "gender": _v(b, "genderLabel"),
            "nationality": _v(b, "countryLabel"),
            "nationality_qid": _qid(b, "country"),
            "genre": _v(b, "genreLabel"),
            "genre_qid": _qid(b, "genre"),
            "notable_work": _v(b, "notableWorkLabel"),
            "imdb_id": _v(b, "imdb"),
            "mb_artist_id": _v(b, "mbid"),
            "website": _v(b, "website"),
            "entity_type": entity_type,
        }
    return _parse


# ---------------------------------------------------------------------------
# CREATIVE WORKS queries
# ---------------------------------------------------------------------------

def _films_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?country ?countryLabel ?lang ?langLabel
  ?duration ?imdb ?tmdb ?director ?directorLabel ?genre ?genreLabel
WHERE {{
  ?item wdt:P31 wd:Q11424 .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P364 ?lang }}
  OPTIONAL {{ ?item wdt:P2047 ?duration }}
  OPTIONAL {{ ?item wdt:P345 ?imdb }}
  OPTIONAL {{ ?item wdt:P4947 ?tmdb }}
  OPTIONAL {{ ?item wdt:P57 ?director }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  FILTER(BOUND(?imdb) || BOUND(?year))
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_film(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "year": _year(b, "year"),
        "country": _v(b, "countryLabel"),
        "country_qid": _qid(b, "country"),
        "language": _v(b, "langLabel"),
        "duration_min": _minutes(b, "duration"),
        "director": _v(b, "directorLabel"),
        "director_qid": _qid(b, "director"),
        "genre": _v(b, "genreLabel"),
        "genre_qid": _qid(b, "genre"),
        "imdb_id": _v(b, "imdb"),
        "tmdb_id": _v(b, "tmdb"),
        "entity_type": "film",
    }


def _tv_series_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?startYear ?endYear ?country ?countryLabel ?lang ?langLabel
  ?network ?networkLabel ?genre ?genreLabel
  ?imdb ?tvdb ?seasons ?episodes
WHERE {{
  VALUES ?type {{ wd:Q5398426 wd:Q1339072 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P580 ?start . BIND(YEAR(?start) AS ?startYear) }}
  OPTIONAL {{ ?item wdt:P582 ?end . BIND(YEAR(?end) AS ?endYear) }}
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P364 ?lang }}
  OPTIONAL {{ ?item wdt:P449 ?network }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P345 ?imdb }}
  OPTIONAL {{ ?item wdt:P5765 ?tvdb }}
  OPTIONAL {{ ?item wdt:P4908 ?seasons }}
  OPTIONAL {{ ?item wdt:P1113 ?episodes }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_tv_series(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "start_year": _year(b, "startYear"),
        "end_year": _year(b, "endYear"),
        "country": _v(b, "countryLabel"),
        "language": _v(b, "langLabel"),
        "network": _v(b, "networkLabel"),
        "network_qid": _qid(b, "network"),
        "genre": _v(b, "genreLabel"),
        "genre_qid": _qid(b, "genre"),
        "seasons": _minutes(b, "seasons"),
        "episodes": _minutes(b, "episodes"),
        "imdb_id": _v(b, "imdb"),
        "thetvdb_id": _v(b, "tvdb"),
        "entity_type": "tv_series",
    }


def _documentaries_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?country ?countryLabel ?lang ?langLabel ?imdb ?director ?directorLabel
WHERE {{
  ?item wdt:P31 wd:Q93204 .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P364 ?lang }}
  OPTIONAL {{ ?item wdt:P345 ?imdb }}
  OPTIONAL {{ ?item wdt:P57 ?director }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_documentary(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "year": _year(b, "year"),
        "country": _v(b, "countryLabel"),
        "language": _v(b, "langLabel"),
        "director": _v(b, "directorLabel"),
        "director_qid": _qid(b, "director"),
        "imdb_id": _v(b, "imdb"),
        "entity_type": "documentary",
    }


def _anime_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?episodes ?studio ?studioLabel ?genre ?genreLabel
  ?anilist ?mal
WHERE {{
  VALUES ?type {{ wd:Q63952888 wd:Q1107 }}
  ?item wdt:P31 ?type .
  ?item wdt:P495 wd:Q17 .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P1113 ?episodes }}
  OPTIONAL {{ ?item wdt:P272 ?studio }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P8729 ?anilist }}
  OPTIONAL {{ ?item wdt:P4086 ?mal }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_anime(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "year": _year(b, "year"),
        "episodes": _minutes(b, "episodes"),
        "studio": _v(b, "studioLabel"),
        "studio_qid": _qid(b, "studio"),
        "genre": _v(b, "genreLabel"),
        "genre_qid": _qid(b, "genre"),
        "anilist_id": _v(b, "anilist"),
        "mal_id": _v(b, "mal"),
        "entity_type": "anime_series",
    }


def _videogames_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?developer ?developerLabel ?publisher ?publisherLabel
  ?platform ?platformLabel ?genre ?genreLabel
  ?steam ?igdb
WHERE {{
  ?item wdt:P31 wd:Q7889 .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P178 ?developer }}
  OPTIONAL {{ ?item wdt:P123 ?publisher }}
  OPTIONAL {{ ?item wdt:P400 ?platform }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P1733 ?steam }}
  OPTIONAL {{ ?item wdt:P5794 ?igdb }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_videogame(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "year": _year(b, "year"),
        "developer": _v(b, "developerLabel"),
        "developer_qid": _qid(b, "developer"),
        "publisher": _v(b, "publisherLabel"),
        "publisher_qid": _qid(b, "publisher"),
        "platform": _v(b, "platformLabel"),
        "platform_qid": _qid(b, "platform"),
        "genre": _v(b, "genreLabel"),
        "genre_qid": _qid(b, "genre"),
        "steam_appid": _v(b, "steam"),
        "igdb_id": _v(b, "igdb"),
        "entity_type": "video_game",
    }


def _albums_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?artist ?artistLabel ?label ?labelLabel ?genre ?genreLabel ?mbid
WHERE {{
  VALUES ?type {{ wd:Q482994 wd:Q209939 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P175 ?artist }}
  OPTIONAL {{ ?item wdt:P264 ?label }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P436 ?mbid }}
  FILTER(BOUND(?artist) || BOUND(?mbid))
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_album(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "year": _year(b, "year"),
        "artist": _v(b, "artistLabel"),
        "artist_qid": _qid(b, "artist"),
        "record_label": _v(b, "labelLabel"),
        "record_label_qid": _qid(b, "label"),
        "genre": _v(b, "genreLabel"),
        "genre_qid": _qid(b, "genre"),
        "mb_release_group_id": _v(b, "mbid"),
        "entity_type": "music_album",
    }


def _manga_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?author ?authorLabel ?genre ?genreLabel ?volumes ?mal
WHERE {{
  VALUES ?type {{ wd:Q21198342 wd:Q13479982 wd:Q1107 }}
  ?item wdt:P31 ?type .
  ?item wdt:P495 wd:Q17 .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P50 ?author }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P1113 ?volumes }}
  OPTIONAL {{ ?item wdt:P4086 ?mal }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_manga(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "year": _year(b, "year"),
        "author": _v(b, "authorLabel"),
        "author_qid": _qid(b, "author"),
        "genre": _v(b, "genreLabel"),
        "genre_qid": _qid(b, "genre"),
        "volumes": _minutes(b, "volumes"),
        "mal_id": _v(b, "mal"),
        "entity_type": "manga",
    }


def _podcasts_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?lang ?langLabel ?publisher ?publisherLabel ?website ?genre ?genreLabel
WHERE {{
  VALUES ?type {{ wd:Q24634210 wd:Q61885251 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P407 ?lang }}
  OPTIONAL {{ ?item wdt:P123 ?publisher }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_podcast(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "language": _v(b, "langLabel"),
        "publisher": _v(b, "publisherLabel"),
        "genre": _v(b, "genreLabel"),
        "website": _v(b, "website"),
        "entity_type": "podcast",
    }


# ---------------------------------------------------------------------------
# TAXONOMY queries
# ---------------------------------------------------------------------------

def _genre_sparql(instance_of_qid: str, offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?parent ?parentLabel
WHERE {{
  ?item wdt:P31 wd:{instance_of_qid} .
  OPTIONAL {{ ?item wdt:P279 ?parent }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_genre(entity_type: str):
    def _parse(b: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "wikidata_id": _qid(b, "item"),
            "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "parent_genre": _v(b, "parentLabel"),
            "parent_genre_qid": _qid(b, "parent"),
            "entity_type": entity_type,
        }
    return _parse


def _instruments_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?family ?familyLabel ?origin ?originLabel
WHERE {{
  VALUES ?type {{ wd:Q34379 wd:Q1254773 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P279 ?family }}
  OPTIONAL {{ ?item wdt:P495 ?origin }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_instrument(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "instrument_family": _v(b, "familyLabel"),
        "family_qid": _qid(b, "family"),
        "origin_country": _v(b, "originLabel"),
        "entity_type": "musical_instrument",
    }


# ---------------------------------------------------------------------------
# ORGANIZATION queries (extended)
# ---------------------------------------------------------------------------

def _org_sparql(instance_of_qids: List[str], entity_type: str, offset: int) -> str:
    values = " ".join(f"wd:{q}" for q in instance_of_qids)
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?inception ?dissolved ?website
WHERE {{
  VALUES ?type {{ {values} }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P576 ?dissolved }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_org(entity_type: str):
    def _parse(b: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "wikidata_id": _qid(b, "item"),
            "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "country": _v(b, "countryLabel"),
            "country_qid": _qid(b, "country"),
            "inception_year": _year(b, "inception"),
            "dissolved_year": _year(b, "dissolved"),
            "website": _v(b, "website"),
            "entity_type": entity_type,
        }
    return _parse


def _music_bands_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?start ?end ?genre ?genreLabel ?mbid ?website
WHERE {{
  VALUES ?type {{ wd:Q215380 wd:Q5741069 wd:Q2088357 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P571 ?start }}
  OPTIONAL {{ ?item wdt:P576 ?end }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P434 ?mbid }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_music_band(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "country_qid": _qid(b, "country"),
        "formed_year": _year(b, "start"),
        "disbanded_year": _year(b, "end"),
        "genre": _v(b, "genreLabel"),
        "genre_qid": _qid(b, "genre"),
        "mb_artist_id": _v(b, "mbid"),
        "website": _v(b, "website"),
        "entity_type": "music_band",
    }


def _game_series_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?developer ?developerLabel ?publisher ?publisherLabel
  ?start ?end ?genre ?genreLabel
WHERE {{
  ?item wdt:P31 wd:Q7058673 .
  OPTIONAL {{ ?item wdt:P178 ?developer }}
  OPTIONAL {{ ?item wdt:P123 ?publisher }}
  OPTIONAL {{ ?item wdt:P580 ?start }}
  OPTIONAL {{ ?item wdt:P582 ?end }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_game_series(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "developer": _v(b, "developerLabel"),
        "publisher": _v(b, "publisherLabel"),
        "start_year": _year(b, "start"),
        "end_year": _year(b, "end"),
        "genre": _v(b, "genreLabel"),
        "genre_qid": _qid(b, "genre"),
        "entity_type": "video_game_series",
    }


def _franchises_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?owner ?ownerLabel ?inception ?website
WHERE {{
  ?item wdt:P31 wd:Q1469839 .
  OPTIONAL {{ ?item wdt:P127 ?owner }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_franchise(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "owner": _v(b, "ownerLabel"),
        "owner_qid": _qid(b, "owner"),
        "inception_year": _year(b, "inception"),
        "website": _v(b, "website"),
        "entity_type": "media_franchise",
    }


def _festivals_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?inception ?location ?locationLabel ?website
WHERE {{
  VALUES ?type {{ wd:Q220505 wd:Q1115575 wd:Q843938 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P276 ?location }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_festival(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "country_qid": _qid(b, "country"),
        "inception_year": _year(b, "inception"),
        "location": _v(b, "locationLabel"),
        "website": _v(b, "website"),
        "entity_type": "festival",
    }


def _award_ceremonies_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?inception ?domain ?domainLabel ?website
WHERE {{
  VALUES ?type {{ wd:Q4504495 wd:Q15275719 wd:Q2490358 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P101 ?domain }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_award_ceremony(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "domain": _v(b, "domainLabel"),
        "inception_year": _year(b, "inception"),
        "website": _v(b, "website"),
        "entity_type": "award_ceremony",
    }


def _tv_channels_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?inception ?dissolved ?website ?genre ?genreLabel
WHERE {{
  VALUES ?type {{ wd:Q2001305 wd:Q15416 wd:Q3669262 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P576 ?dissolved }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_tv_channel(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "country_qid": _qid(b, "country"),
        "inception_year": _year(b, "inception"),
        "dissolved_year": _year(b, "dissolved"),
        "genre": _v(b, "genreLabel"),
        "website": _v(b, "website"),
        "entity_type": "tv_channel",
    }


# ---------------------------------------------------------------------------
# Additional SPARQL helpers — new work types, people, orgs
# ---------------------------------------------------------------------------

def _film_type_sparql(qids: List[str], offset: int) -> str:
    """Generic film-like works query (animated films, shorts, docs, etc.)."""
    values = " ".join(f"wd:{q}" for q in qids)
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?country ?countryLabel ?lang ?langLabel
  ?duration ?imdb ?director ?directorLabel ?genre ?genreLabel
WHERE {{
  VALUES ?type {{ {values} }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P364 ?lang }}
  OPTIONAL {{ ?item wdt:P2047 ?duration }}
  OPTIONAL {{ ?item wdt:P345 ?imdb }}
  OPTIONAL {{ ?item wdt:P57 ?director }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _tv_type_sparql(qids: List[str], offset: int) -> str:
    """Generic TV-like works query (miniseries, reality TV, talk shows, etc.)."""
    values = " ".join(f"wd:{q}" for q in qids)
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?startYear ?endYear ?country ?countryLabel ?lang ?langLabel
  ?network ?networkLabel ?genre ?genreLabel ?imdb ?episodes
WHERE {{
  VALUES ?type {{ {values} }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P580 ?start . BIND(YEAR(?start) AS ?startYear) }}
  OPTIONAL {{ ?item wdt:P582 ?end . BIND(YEAR(?end) AS ?endYear) }}
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P364 ?lang }}
  OPTIONAL {{ ?item wdt:P449 ?network }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P345 ?imdb }}
  OPTIONAL {{ ?item wdt:P1113 ?episodes }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _stage_work_sparql(qids: List[str], offset: int) -> str:
    values = " ".join(f"wd:{q}" for q in qids)
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?country ?countryLabel ?lang ?langLabel
  ?composer ?composerLabel ?author ?authorLabel ?genre ?genreLabel
WHERE {{
  VALUES ?type {{ {values} }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P495 ?country }}
  OPTIONAL {{ ?item wdt:P364 ?lang }}
  OPTIONAL {{ ?item wdt:P86 ?composer }}
  OPTIONAL {{ ?item wdt:P50 ?author }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_stage_work(entity_type: str):
    def _parse(b: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "wikidata_id": _qid(b, "item"),
            "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "year": _year(b, "year"),
            "country": _v(b, "countryLabel"),
            "language": _v(b, "langLabel"),
            "composer": _v(b, "composerLabel"),
            "composer_qid": _qid(b, "composer"),
            "author": _v(b, "authorLabel"),
            "author_qid": _qid(b, "author"),
            "genre": _v(b, "genreLabel"),
            "entity_type": entity_type,
        }
    return _parse


def _print_work_sparql(qids: List[str], offset: int) -> str:
    values = " ".join(f"wd:{q}" for q in qids)
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?author ?authorLabel ?publisher ?publisherLabel
  ?lang ?langLabel ?genre ?genreLabel ?volumes ?isbn
WHERE {{
  VALUES ?type {{ {values} }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P50 ?author }}
  OPTIONAL {{ ?item wdt:P123 ?publisher }}
  OPTIONAL {{ ?item wdt:P407 ?lang }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P1113 ?volumes }}
  OPTIONAL {{ ?item wdt:P212 ?isbn }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_print_work(entity_type: str):
    def _parse(b: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "wikidata_id": _qid(b, "item"),
            "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "year": _year(b, "year"),
            "author": _v(b, "authorLabel"),
            "author_qid": _qid(b, "author"),
            "publisher": _v(b, "publisherLabel"),
            "publisher_qid": _qid(b, "publisher"),
            "language": _v(b, "langLabel"),
            "genre": _v(b, "genreLabel"),
            "volumes": _minutes(b, "volumes"),
            "isbn": _v(b, "isbn"),
            "entity_type": entity_type,
        }
    return _parse


def _audio_work_sparql(qids: List[str], offset: int) -> str:
    """Audio dramas, radio programs, audiobooks."""
    values = " ".join(f"wd:{q}" for q in qids)
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?startYear ?endYear ?lang ?langLabel
  ?network ?networkLabel ?genre ?genreLabel
  ?author ?authorLabel ?narrator ?narratorLabel
WHERE {{
  VALUES ?type {{ {values} }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P580 ?start . BIND(YEAR(?start) AS ?startYear) }}
  OPTIONAL {{ ?item wdt:P582 ?end . BIND(YEAR(?end) AS ?endYear) }}
  OPTIONAL {{ ?item wdt:P407 ?lang }}
  OPTIONAL {{ ?item wdt:P449 ?network }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P50 ?author }}
  OPTIONAL {{ ?item wdt:P161 ?narrator }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_audio_work(entity_type: str):
    def _parse(b: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "wikidata_id": _qid(b, "item"),
            "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "start_year": _year(b, "startYear"),
            "end_year": _year(b, "endYear"),
            "language": _v(b, "langLabel"),
            "network": _v(b, "networkLabel"),
            "genre": _v(b, "genreLabel"),
            "author": _v(b, "authorLabel"),
            "narrator": _v(b, "narratorLabel"),
            "narrator_qid": _qid(b, "narrator"),
            "entity_type": entity_type,
        }
    return _parse


def _audiobook_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?author ?authorLabel ?narrator ?narratorLabel
  ?lang ?langLabel ?duration ?isbn
WHERE {{
  VALUES ?type {{ wd:Q1345536 wd:Q424598 wd:Q6784261 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P50 ?author }}
  OPTIONAL {{ ?item wdt:P161 ?narrator }}
  OPTIONAL {{ ?item wdt:P407 ?lang }}
  OPTIONAL {{ ?item wdt:P2047 ?duration }}
  OPTIONAL {{ ?item wdt:P212 ?isbn }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_audiobook(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "year": _year(b, "year"),
        "author": _v(b, "authorLabel"),
        "author_qid": _qid(b, "author"),
        "narrator": _v(b, "narratorLabel"),
        "narrator_qid": _qid(b, "narrator"),
        "language": _v(b, "langLabel"),
        "duration_min": _minutes(b, "duration"),
        "isbn": _v(b, "isbn"),
        "entity_type": "audiobook",
    }


def _music_video_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?artist ?artistLabel ?director ?directorLabel
  ?song ?songLabel ?lang ?langLabel
WHERE {{
  ?item wdt:P31 wd:Q26399 .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P175 ?artist }}
  OPTIONAL {{ ?item wdt:P57 ?director }}
  OPTIONAL {{ ?item wdt:P658 ?song }}
  OPTIONAL {{ ?item wdt:P407 ?lang }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_music_video(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "year": _year(b, "year"),
        "artist": _v(b, "artistLabel"),
        "artist_qid": _qid(b, "artist"),
        "director": _v(b, "directorLabel"),
        "director_qid": _qid(b, "director"),
        "song": _v(b, "songLabel"),
        "language": _v(b, "langLabel"),
        "entity_type": "music_video",
    }


def _board_game_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?year ?designer ?designerLabel ?publisher ?publisherLabel
  ?genre ?genreLabel ?players_min ?players_max
WHERE {{
  VALUES ?type {{ wd:Q131436 wd:Q1643723 wd:Q734698 wd:Q27132364 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  OPTIONAL {{ ?item wdt:P178 ?designer }}
  OPTIONAL {{ ?item wdt:P123 ?publisher }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P1872 ?players_min }}
  OPTIONAL {{ ?item wdt:P1873 ?players_max }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_board_game(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "year": _year(b, "year"),
        "designer": _v(b, "designerLabel"),
        "designer_qid": _qid(b, "designer"),
        "publisher": _v(b, "publisherLabel"),
        "publisher_qid": _qid(b, "publisher"),
        "genre": _v(b, "genreLabel"),
        "players_min": _minutes(b, "players_min"),
        "players_max": _minutes(b, "players_max"),
        "entity_type": "board_game",
    }


def _venue_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?city ?cityLabel ?capacity ?inception ?website
WHERE {{
  VALUES ?type {{ wd:Q17350442 wd:Q24354 wd:Q483110 wd:Q1573141 wd:Q207694 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P131 ?city }}
  OPTIONAL {{ ?item wdt:P1083 ?capacity }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_venue(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "city": _v(b, "cityLabel"),
        "city_qid": _qid(b, "city"),
        "capacity": _minutes(b, "capacity"),
        "inception_year": _year(b, "inception"),
        "website": _v(b, "website"),
        "entity_type": "concert_venue",
    }


def _music_festival_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?city ?cityLabel ?inception ?genre ?genreLabel ?website
WHERE {{
  ?item wdt:P31 wd:Q132241 .
  ?item wdt:P101 wd:Q638 .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P276 ?city }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_music_festival(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "city": _v(b, "cityLabel"),
        "inception_year": _year(b, "inception"),
        "genre": _v(b, "genreLabel"),
        "website": _v(b, "website"),
        "entity_type": "music_festival",
    }


def _orch_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?city ?cityLabel ?inception ?dissolved ?website
WHERE {{
  VALUES ?type {{ wd:Q42998 wd:Q131186 wd:Q1466250 wd:Q860861 wd:Q2738074 wd:Q5487732 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P131 ?city }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P576 ?dissolved }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_orch(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "city": _v(b, "cityLabel"),
        "inception_year": _year(b, "inception"),
        "dissolved_year": _year(b, "dissolved"),
        "website": _v(b, "website"),
        "entity_type": "performing_arts_ensemble",
    }


def _youtube_channels_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?inception ?subscribers ?genre ?genreLabel ?website
WHERE {{
  VALUES ?type {{ wd:Q13366104 wd:Q24634210 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P3744 ?subscribers }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_youtube_channel(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "inception_year": _year(b, "inception"),
        "subscribers": _minutes(b, "subscribers"),
        "genre": _v(b, "genreLabel"),
        "website": _v(b, "website"),
        "entity_type": "youtube_channel",
    }


def _literary_awards_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?inception ?domain ?domainLabel ?website
WHERE {{
  VALUES ?type {{ wd:Q378427 wd:Q1364556 wd:Q4509981 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P101 ?domain }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_literary_award(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "domain": _v(b, "domainLabel"),
        "inception_year": _year(b, "inception"),
        "website": _v(b, "website"),
        "entity_type": "literary_award",
    }


def _recording_studio_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?city ?cityLabel ?inception ?dissolved ?website
WHERE {{
  VALUES ?type {{ wd:Q2996943 wd:Q1641044 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P131 ?city }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P576 ?dissolved }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_recording_studio(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "city": _v(b, "cityLabel"),
        "inception_year": _year(b, "inception"),
        "dissolved_year": _year(b, "dissolved"),
        "website": _v(b, "website"),
        "entity_type": "recording_studio",
    }


def _esports_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription
  ?country ?countryLabel ?inception ?dissolved ?website
WHERE {{
  VALUES ?type {{ wd:Q1194970 wd:Q15140312 wd:Q15832596 }}
  ?item wdt:P31 ?type .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P576 ?dissolved }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_esports(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "country": _v(b, "countryLabel"),
        "inception_year": _year(b, "inception"),
        "dissolved_year": _year(b, "dissolved"),
        "website": _v(b, "website"),
        "entity_type": "esports_organization",
    }


# ---------------------------------------------------------------------------
# Spotify ID queries  (P1902=artist, P2205=album, P2207=track, P2206=show)
# ---------------------------------------------------------------------------

def _spotify_artists_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?spotify_id ?mb_id ?country ?countryLabel
WHERE {{
  ?item wdt:P1902 ?spotify_id .
  OPTIONAL {{ ?item wdt:P434 ?mb_id }}
  OPTIONAL {{ ?item wdt:P17 ?country }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_spotify_artist(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "spotify_artist_id": _v(b, "spotify_id"),
        "spotify_url": f"https://open.spotify.com/artist/{_v(b, 'spotify_id')}" if _v(b, "spotify_id") else None,
        "mb_id": _v(b, "mb_id"),
        "country": _v(b, "countryLabel"),
        "inception_year": _year(b, "inception"),
        "genre": _v(b, "genreLabel"),
        "genre_qid": _qid(b, "genre"),
        "website": _v(b, "website"),
        "entity_type": "spotify_artist",
    }


def _spotify_albums_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?spotify_id ?mb_id ?artist ?artistLabel ?year
WHERE {{
  ?item wdt:P2205 ?spotify_id .
  OPTIONAL {{ ?item wdt:P435 ?mb_id }}
  OPTIONAL {{ ?item wdt:P175 ?artist }}
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_spotify_album(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "spotify_album_id": _v(b, "spotify_id"),
        "spotify_url": f"https://open.spotify.com/album/{_v(b, 'spotify_id')}" if _v(b, "spotify_id") else None,
        "mb_id": _v(b, "mb_id"),
        "artist": _v(b, "artistLabel"),
        "artist_qid": _qid(b, "artist"),
        "year": _year(b, "year"),
        "genre": _v(b, "genreLabel"),
        "entity_type": "spotify_album",
    }


def _spotify_tracks_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?spotify_id ?mb_id ?artist ?artistLabel ?year
WHERE {{
  ?item wdt:P2207 ?spotify_id .
  OPTIONAL {{ ?item wdt:P436 ?mb_id }}
  OPTIONAL {{ ?item wdt:P175 ?artist }}
  OPTIONAL {{ ?item wdt:P577 ?pubDate . BIND(YEAR(?pubDate) AS ?year) }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_spotify_track(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "spotify_track_id": _v(b, "spotify_id"),
        "spotify_url": f"https://open.spotify.com/track/{_v(b, 'spotify_id')}" if _v(b, "spotify_id") else None,
        "mb_id": _v(b, "mb_id"),
        "artist": _v(b, "artistLabel"),
        "artist_qid": _qid(b, "artist"),
        "album": _v(b, "albumLabel"),
        "album_qid": _qid(b, "album"),
        "year": _year(b, "year"),
        "duration_minutes": _minutes(b, "duration"),
        "entity_type": "spotify_track",
    }


def _spotify_shows_sparql(offset: int) -> str:
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?spotify_id
  ?country ?countryLabel ?inception ?genre ?genreLabel ?website
WHERE {{
  ?item wdt:P2206 ?spotify_id .
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P136 ?genre }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,native" }}
}}
ORDER BY ?item
LIMIT {CHUNK}
OFFSET {offset}
"""


def _parse_spotify_show(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wikidata_id": _qid(b, "item"),
        "label_en": _v(b, "itemLabel"),
        "description_en": _v(b, "itemDescription"),
        "spotify_show_id": _v(b, "spotify_id"),
        "spotify_url": f"https://open.spotify.com/show/{_v(b, 'spotify_id')}" if _v(b, "spotify_id") else None,
        "country": _v(b, "countryLabel"),
        "inception_year": _year(b, "inception"),
        "genre": _v(b, "genreLabel"),
        "website": _v(b, "website"),
        "entity_type": "spotify_show",
    }


# ---------------------------------------------------------------------------
# Master query registry
# ---------------------------------------------------------------------------

def _mk(name: str, etype: str, sparql_fn: Callable[[int], str],
        parse_fn: Callable[[Dict], Dict], chunk: int = CHUNK) -> QuerySpec:
    return QuerySpec(name=name, entity_type=etype,
                     build_sparql=sparql_fn, parse_binding=parse_fn, chunk=chunk)


def _mkp(name: str, etype: str, sparql_fn: Callable[[int], str],
         parse_fn: Callable[[Dict], Dict]) -> QuerySpec:
    """Person query — uses smaller PEOPLE_CHUNK."""
    return _mk(name, etype, sparql_fn, parse_fn, chunk=PEOPLE_CHUNK)


QUERIES: List[QuerySpec] = [
    # -- People -----------------------------------------------------------
    _mkp("film_directors", "film_director",
         lambda o: _people_sparql(["Q2526255"], "", o),
         _parse_person("film_director")),
    _mkp("film_actors", "film_actor",
         lambda o: _people_sparql(["Q33999", "Q10800557"], "", o),
         _parse_person("film_actor")),
    _mkp("screenwriters", "screenwriter",
         lambda o: _people_sparql(["Q28389"], "", o),
         _parse_person("screenwriter")),
    _mkp("film_producers_people", "film_producer",
         lambda o: _people_sparql(["Q3282637"], "", o),
         _parse_person("film_producer")),
    _mkp("singers", "singer",
         lambda o: _music_people_sparql(["Q177220", "Q1371941"], o),
         _parse_music_person("singer")),
    _mkp("musicians_people", "musician",
         lambda o: _music_people_sparql(["Q488205", "Q639669"], o),
         _parse_music_person("musician")),
    _mkp("music_composers", "music_composer",
         lambda o: _music_people_sparql(["Q36834"], o),
         _parse_music_person("music_composer")),
    _mkp("djs", "dj",
         lambda o: _music_people_sparql(["Q130857", "Q4610556"], o),
         _parse_music_person("dj")),
    _mkp("authors", "author",
         lambda o: _people_sparql(["Q36180", "Q6625963", "Q4853732"], "", o),
         _parse_person("author")),
    _mkp("voice_actors", "voice_actor",
         lambda o: _people_sparql(["Q2405480"], "", o),
         _parse_person("voice_actor")),
    _mkp("manga_artists", "manga_artist",
         lambda o: _people_sparql(["Q14941078", "Q10862983"], "", o),
         _parse_person("manga_artist")),
    _mkp("anime_directors", "anime_director",
         lambda o: _people_sparql(["Q2526255"], "?item wdt:P495 wd:Q17 .", o),
         _parse_person("anime_director")),
    _mkp("game_designers", "game_designer",
         lambda o: _people_sparql(["Q5189795", "Q1326886"], "", o),
         _parse_person("game_designer")),
    _mkp("podcasters", "podcaster",
         lambda o: _people_sparql(["Q15627169"],
             "FILTER(!BOUND(?birthDate) || YEAR(?birthDate) > 1940)", o),
         _parse_person("podcaster")),
    _mkp("stand_up_comedians", "comedian",
         lambda o: _people_sparql(["Q4173446", "Q1114448"], "", o),
         _parse_person("comedian")),
    _mkp("film_score_composers", "film_score_composer",
         lambda o: _people_sparql(["Q36834", "Q214917"], "", o),
         _parse_person("film_score_composer")),

    # -- Creative works ---------------------------------------------------
    _mk("films", "film", _films_sparql, _parse_film),
    _mk("tv_series", "tv_series", _tv_series_sparql, _parse_tv_series),
    _mk("documentaries", "documentary", _documentaries_sparql, _parse_documentary),
    _mk("anime_series", "anime_series", _anime_sparql, _parse_anime),
    _mk("video_games_works", "video_game", _videogames_sparql, _parse_videogame),
    _mk("music_albums", "music_album", _albums_sparql, _parse_album),
    _mk("manga_works", "manga", _manga_sparql, _parse_manga),
    _mk("podcast_shows", "podcast", _podcasts_sparql, _parse_podcast),

    # -- Taxonomies -------------------------------------------------------
    _mk("music_genres", "music_genre",
        lambda o: _genre_sparql("Q188451", o),
        _parse_genre("music_genre")),
    _mk("film_genres", "film_genre",
        lambda o: _genre_sparql("Q201658", o),
        _parse_genre("film_genre")),
    _mk("tv_genres", "tv_genre",
        lambda o: _genre_sparql("Q15961987", o),
        _parse_genre("tv_genre")),
    _mk("video_game_genres", "video_game_genre",
        lambda o: _genre_sparql("Q659563", o),
        _parse_genre("video_game_genre")),
    _mk("literary_genres", "literary_genre",
        lambda o: _genre_sparql("Q223393", o),
        _parse_genre("literary_genre")),
    _mk("music_instruments", "musical_instrument",
        _instruments_sparql, _parse_instrument),

    # -- Organizations ----------------------------------------------------
    _mk("film_studios", "film_studio",
        lambda o: _org_sparql(["Q231002", "Q17324419", "Q18008791"], "film_studio", o),
        _parse_org("film_studio")),
    _mk("record_labels", "record_label",
        lambda o: _org_sparql(["Q18127"], "record_label", o),
        _parse_org("record_label")),
    _mk("book_publishers", "book_publisher",
        lambda o: _org_sparql(["Q2085381", "Q1114461"], "book_publisher", o),
        _parse_org("book_publisher")),
    _mk("game_studios", "game_studio",
        lambda o: _org_sparql(["Q5154439", "Q210167", "Q1137109"], "game_studio", o),
        _parse_org("game_studio")),
    _mk("animation_studios", "animation_studio",
        lambda o: _org_sparql(["Q17359456", "Q195"], "animation_studio", o),
        _parse_org("animation_studio")),
    _mk("streaming_services", "streaming_service",
        lambda o: _org_sparql(["Q15895784", "Q18127046", "Q110769328"], "streaming_service", o),
        _parse_org("streaming_service")),
    _mk("news_agencies", "news_agency",
        lambda o: _org_sparql(["Q192283", "Q1153191"], "news_agency", o),
        _parse_org("news_agency")),
    _mk("film_distributors", "film_distributor",
        lambda o: _org_sparql(["Q17320644", "Q18008791"], "film_distributor", o),
        _parse_org("film_distributor")),
    _mk("talent_agencies", "talent_agency",
        lambda o: _org_sparql(["Q936006"], "talent_agency", o),
        _parse_org("talent_agency")),
    _mk("radio_stations", "radio_station",
        lambda o: _org_sparql(["Q14350", "Q1800394"], "radio_station", o),
        _parse_org("radio_station")),

    # -- Other entities ---------------------------------------------------
    _mk("music_bands", "music_band", _music_bands_sparql, _parse_music_band),
    _mk("tv_channels", "tv_channel", _tv_channels_sparql, _parse_tv_channel),
    _mk("video_game_series", "video_game_series", _game_series_sparql, _parse_game_series),
    _mk("media_franchises", "media_franchise", _franchises_sparql, _parse_franchise),
    _mk("film_festivals", "film_festival", _festivals_sparql, _parse_festival),
    _mk("award_ceremonies", "award_ceremony", _award_ceremonies_sparql, _parse_award_ceremony),

    # -- Additional People (audio/text/stage) -----------------------------
    _mkp("record_producers", "record_producer",
         lambda o: _music_people_sparql(["Q19808726"], o),
         _parse_music_person("record_producer")),
    _mkp("television_hosts", "television_host",
         lambda o: _people_sparql(["Q13382533", "Q16144998"], "", o),
         _parse_person("television_host")),
    _mkp("novelists", "novelist",
         lambda o: _people_sparql(["Q6625963"], "", o),
         _parse_person("novelist")),
    _mkp("orchestral_conductors", "conductor",
         lambda o: _music_people_sparql(["Q158852", "Q5278032"], o),
         _parse_music_person("conductor")),
    _mkp("lyricists", "lyricist",
         lambda o: _music_people_sparql(["Q1278335"], o),
         _parse_music_person("lyricist")),
    _mkp("cartoonists", "cartoonist",
         lambda o: _people_sparql(["Q866657", "Q531995"], "", o),
         _parse_person("cartoonist")),
    _mkp("illustrators", "illustrator",
         lambda o: _people_sparql(["Q644687"], "", o),
         _parse_person("illustrator")),
    _mkp("choreographers", "choreographer",
         lambda o: _people_sparql(["Q1809130"], "", o),
         _parse_person("choreographer")),
    _mkp("narrators", "narrator",
         lambda o: _people_sparql(["Q2865819"], "", o),
         _parse_person("narrator")),
    _mkp("radio_hosts", "radio_host",
         lambda o: _people_sparql(["Q28220070", "Q1643578"], "", o),
         _parse_person("radio_host")),
    _mkp("stunt_performers", "stunt_performer",
         lambda o: _people_sparql(["Q2133309"], "", o),
         _parse_person("stunt_performer")),
    _mkp("radio_actors", "radio_actor",
         lambda o: _people_sparql(["Q3282637", "Q2405480"], "?item wdt:P737 [] . FILTER NOT EXISTS { ?item wdt:P106 wd:Q33999 }", o),
         _parse_person("radio_actor")),

    # -- Additional film/video works --------------------------------------
    _mk("animated_films", "animated_film",
        lambda o: _film_type_sparql(["Q202866"], o),
        lambda b: {
            "wikidata_id": _qid(b, "item"), "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"), "year": _year(b, "year"),
            "country": _v(b, "countryLabel"), "language": _v(b, "langLabel"),
            "duration_min": _minutes(b, "duration"), "imdb_id": _v(b, "imdb"),
            "director": _v(b, "directorLabel"), "director_qid": _qid(b, "director"),
            "genre": _v(b, "genreLabel"), "entity_type": "animated_film",
        }),
    _mk("short_films", "short_film",
        lambda o: _film_type_sparql(["Q24862"], o),
        lambda b: {
            "wikidata_id": _qid(b, "item"), "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"), "year": _year(b, "year"),
            "country": _v(b, "countryLabel"), "language": _v(b, "langLabel"),
            "duration_min": _minutes(b, "duration"), "imdb_id": _v(b, "imdb"),
            "director": _v(b, "directorLabel"), "director_qid": _qid(b, "director"),
            "genre": _v(b, "genreLabel"), "entity_type": "short_film",
        }),
    _mk("music_videos", "music_video", _music_video_sparql, _parse_music_video),

    # -- Additional TV/web works ------------------------------------------
    _mk("animated_series", "animated_series",
        lambda o: _tv_type_sparql(["Q581714", "Q220898"], o),
        lambda b: {
            "wikidata_id": _qid(b, "item"), "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "start_year": _year(b, "startYear"), "end_year": _year(b, "endYear"),
            "country": _v(b, "countryLabel"), "language": _v(b, "langLabel"),
            "network": _v(b, "networkLabel"), "network_qid": _qid(b, "network"),
            "genre": _v(b, "genreLabel"), "imdb_id": _v(b, "imdb"),
            "episodes": _minutes(b, "episodes"), "entity_type": "animated_series",
        }),
    _mk("miniseries", "miniseries",
        lambda o: _tv_type_sparql(["Q1259759"], o),
        lambda b: {
            "wikidata_id": _qid(b, "item"), "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "start_year": _year(b, "startYear"), "end_year": _year(b, "endYear"),
            "country": _v(b, "countryLabel"), "language": _v(b, "langLabel"),
            "network": _v(b, "networkLabel"), "genre": _v(b, "genreLabel"),
            "imdb_id": _v(b, "imdb"), "episodes": _minutes(b, "episodes"),
            "entity_type": "miniseries",
        }),
    _mk("reality_tv_shows", "reality_tv_show",
        lambda o: _tv_type_sparql(["Q926413"], o),
        lambda b: {
            "wikidata_id": _qid(b, "item"), "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "start_year": _year(b, "startYear"), "end_year": _year(b, "endYear"),
            "country": _v(b, "countryLabel"), "language": _v(b, "langLabel"),
            "network": _v(b, "networkLabel"), "genre": _v(b, "genreLabel"),
            "episodes": _minutes(b, "episodes"), "entity_type": "reality_tv_show",
        }),
    _mk("talk_shows", "talk_show",
        lambda o: _tv_type_sparql(["Q1272107"], o),
        lambda b: {
            "wikidata_id": _qid(b, "item"), "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "start_year": _year(b, "startYear"), "end_year": _year(b, "endYear"),
            "country": _v(b, "countryLabel"), "language": _v(b, "langLabel"),
            "network": _v(b, "networkLabel"), "genre": _v(b, "genreLabel"),
            "episodes": _minutes(b, "episodes"), "entity_type": "talk_show",
        }),
    _mk("game_shows", "game_show",
        lambda o: _tv_type_sparql(["Q929467"], o),
        lambda b: {
            "wikidata_id": _qid(b, "item"), "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "start_year": _year(b, "startYear"), "end_year": _year(b, "endYear"),
            "country": _v(b, "countryLabel"), "language": _v(b, "langLabel"),
            "network": _v(b, "networkLabel"), "genre": _v(b, "genreLabel"),
            "episodes": _minutes(b, "episodes"), "entity_type": "game_show",
        }),
    _mk("web_series", "web_series",
        lambda o: _tv_type_sparql(["Q526877", "Q24634210"], o),
        lambda b: {
            "wikidata_id": _qid(b, "item"), "label_en": _v(b, "itemLabel"),
            "description_en": _v(b, "itemDescription"),
            "start_year": _year(b, "startYear"), "end_year": _year(b, "endYear"),
            "country": _v(b, "countryLabel"), "language": _v(b, "langLabel"),
            "network": _v(b, "networkLabel"), "genre": _v(b, "genreLabel"),
            "episodes": _minutes(b, "episodes"), "entity_type": "web_series",
        }),

    # -- Stage and performing arts works ----------------------------------
    _mk("stage_plays", "stage_play",
        lambda o: _stage_work_sparql(["Q25379", "Q11635"], o),
        _parse_stage_work("stage_play")),
    _mk("musicals", "musical",
        lambda o: _stage_work_sparql(["Q2736"], o),
        _parse_stage_work("musical")),
    _mk("operas", "opera",
        lambda o: _stage_work_sparql(["Q1344", "Q8341", "Q189539"], o),
        _parse_stage_work("opera")),

    # -- Audio works ------------------------------------------------------
    _mk("radio_programs", "radio_program",
        lambda o: _audio_work_sparql(["Q30461", "Q268592"], o),
        _parse_audio_work("radio_program")),
    _mk("audio_dramas", "audio_drama",
        lambda o: _audio_work_sparql(["Q573347", "Q1765879", "Q2945537"], o),
        _parse_audio_work("audio_drama")),
    _mk("audiobooks", "audiobook", _audiobook_sparql, _parse_audiobook),

    # -- Print/comics works -----------------------------------------------
    _mk("graphic_novels", "graphic_novel",
        lambda o: _print_work_sparql(["Q1131117", "Q25058", "Q242665"], o),
        _parse_print_work("graphic_novel")),
    _mk("comic_book_series", "comic_book_series",
        lambda o: _print_work_sparql(["Q14406742", "Q1004"], o),
        _parse_print_work("comic_book_series")),
    _mk("light_novels", "light_novel",
        lambda o: _print_work_sparql(["Q746219"], o),
        _parse_print_work("light_novel")),
    _mk("visual_novels", "visual_novel",
        lambda o: _print_work_sparql(["Q689445"], o),
        _parse_print_work("visual_novel")),
    _mk("novels", "novel",
        lambda o: _print_work_sparql(["Q8261"], o),
        _parse_print_work("novel")),

    # -- Tabletop / board games -------------------------------------------
    _mk("board_games", "board_game", _board_game_sparql, _parse_board_game),

    # -- Additional Taxonomies --------------------------------------------
    _mk("manga_genres", "manga_genre",
        lambda o: _genre_sparql("Q20800053", o),
        _parse_genre("manga_genre")),
    _mk("anime_genres", "anime_genre",
        lambda o: _genre_sparql("Q1107", o),
        _parse_genre("anime_genre")),
    _mk("podcast_categories", "podcast_category",
        lambda o: _genre_sparql("Q23902", o),
        _parse_genre("podcast_category")),
    _mk("board_game_mechanics", "board_game_mechanic",
        lambda o: _genre_sparql("Q1054574", o),
        _parse_genre("board_game_mechanic")),

    # -- Additional Organizations -----------------------------------------
    _mk("orchestras_ensembles", "performing_arts_ensemble",
        _orch_sparql, _parse_orch),
    _mk("concert_venues", "concert_venue", _venue_sparql, _parse_venue),
    _mk("music_festivals", "music_festival", _music_festival_sparql, _parse_music_festival),
    _mk("recording_studios", "recording_studio",
        _recording_studio_sparql, _parse_recording_studio),
    _mk("youtube_channels", "youtube_channel",
        _youtube_channels_sparql, _parse_youtube_channel),
    _mk("literary_awards", "literary_award",
        _literary_awards_sparql, _parse_literary_award),
    _mk("esports_organizations", "esports_organization",
        _esports_sparql, _parse_esports),
    # -- Spotify IDs ----------------------------------------------------------
    _mk("spotify_artists", "spotify_artist",
        _spotify_artists_sparql, _parse_spotify_artist),
    _mk("spotify_albums", "spotify_album",
        _spotify_albums_sparql, _parse_spotify_album),
    _mk("spotify_tracks", "spotify_track",
        _spotify_tracks_sparql, _parse_spotify_track),
    _mk("spotify_shows", "spotify_show",
        _spotify_shows_sparql, _parse_spotify_show),
]

QUERY_INDEX = {q.name: q for q in QUERIES}


# ---------------------------------------------------------------------------
# Engine wiring
# ---------------------------------------------------------------------------

@register
class WikidataEntitiesSource(PaginatedJSONSource):
    name = "wikidata_entities"
    id_field = "wikidata_id"
    default_delay = 2.0

    base = SPARQL_URL
    accept = "application/sparql-results+json"
    user_agent = "metadatarr-scraper/1.0 (https://github.com/TigreGotico/metadatarr)"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self.queries: List[QuerySpec] = QUERIES

    @classmethod
    def add_cli_arguments(cls, parser) -> None:
        parser.add_argument("--query", default=None, help="Run only this query name")
        parser.add_argument("--list-queries", action="store_true",
                            help="Print all registered query names and exit")

    def configure(self, args) -> None:
        if getattr(args, "list_queries", False):
            for spec in QUERIES:
                print(f"  {spec.name:<35} -> {spec.entity_type}")
            raise SystemExit(0)

        only_query = getattr(args, "query", None)
        if only_query:
            if only_query not in QUERY_INDEX:
                raise SystemExit(
                    f"Unknown query '{only_query}'. Use --list-queries to see available names.")
            self.queries = [QUERY_INDEX[only_query]]
        else:
            self.queries = QUERIES

    def initial_cursor(self) -> Dict[str, int]:
        return {"qidx": 0, "offset": 0}

    def _sparql(self, query: str) -> List[Dict[str, Any]]:
        headers = {"User-Agent": self.user_agent, "Accept": self.accept}
        self.throttle.wait()
        for attempt in range(3):
            try:
                resp = self.session().get(
                    self.base, params={"query": query, "format": "json"},
                    headers=headers, timeout=180,
                )
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 60))
                    time.sleep(wait)
                    continue
                if resp.status_code == 503:
                    time.sleep(30)
                    continue
                resp.raise_for_status()
                return resp.json().get("results", {}).get("bindings", [])
            except Exception:
                time.sleep(10)
        return []

    def fetch(self, cursor: Dict[str, int]):
        qidx = int(cursor.get("qidx", 0))
        offset = int(cursor.get("offset", 0))
        queries = self.queries

        if qidx >= len(queries):
            return [], None
        spec = queries[qidx]

        sparql_q = spec.build_sparql(offset)
        bindings = self._sparql(sparql_q)

        if not bindings:
            next_qidx = qidx + 1
            next_cursor = {"qidx": next_qidx, "offset": 0} if next_qidx < len(queries) else None
            return [], next_cursor

        rows = []
        for b in bindings:
            row = spec.parse_binding(b)
            if row.get("wikidata_id"):
                rows.append(row)

        if len(bindings) < spec.chunk:
            next_qidx = qidx + 1
            next_cursor = {"qidx": next_qidx, "offset": 0} if next_qidx < len(queries) else None
        else:
            next_cursor = {"qidx": qidx, "offset": offset + spec.chunk}
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(WikidataEntitiesSource))
