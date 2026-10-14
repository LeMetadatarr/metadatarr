# SPDX-License-Identifier: Apache-2.0
"""TMDB, available when ``TMDB_API_KEY`` is set in metadatarr's environment:
movies, collections, series with seasons, seasons with episodes, cast and crew,
and people with their combined filmography.

TMDB gives a season no identifier of its own that its API can be asked by, so
a season is named ``<series tmdb id>/<season number>`` under the ``tmdb``
scheme. An IMDb id is translated through TMDB's ``find`` endpoint."""
from __future__ import annotations

import os
from typing import List, Optional

from metadatarr.catalog import _http
from metadatarr.catalog.base import CatalogSource, register_source
from metadatarr.catalog.roles import normalise_role
from metadatarr.catalog.shapes import Credit, Item, Person, PersonDetails, iso_date, merge_credits, year_of
from metadatarr.catalog.sources._util import as_int, ids, minutes, plain_text

API = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p/original"


def _img(path: Optional[str]) -> str:
    return f"{IMAGES}{path}" if path else ""


def _movie(m: dict, position: Optional[float] = None) -> Item:
    ext = m.get("external_ids") or {}
    return Item(
        kind="movie", title=m.get("title") or "", original_title=m.get("original_title") or "",
        year=year_of(m.get("release_date")), release_date=iso_date(m.get("release_date")),
        runtime_min=minutes(m.get("runtime")), overview=plain_text(m.get("overview")),
        poster_url=_img(m.get("poster_path")), position=position,
        ext_ids=ids(tmdb=m.get("id"), imdb=m.get("imdb_id") or ext.get("imdb_id"), wikidata=ext.get("wikidata_id")),
        extra={k: v for k, v in {
            "genres": [g.get("name") for g in m.get("genres") or [] if g.get("name")],
            "original_language": m.get("original_language"), "status": m.get("status"),
            "collection": ids(tmdb=(m.get("belongs_to_collection") or {}).get("id"),
                              name=(m.get("belongs_to_collection") or {}).get("name"))}.items() if v},
    )


def _series(s: dict) -> Item:
    ext = s.get("external_ids") or {}
    runtimes = s.get("episode_run_time") or []
    return Item(
        kind="series", title=s.get("name") or "", original_title=s.get("original_name") or "",
        year=year_of(s.get("first_air_date")), release_date=iso_date(s.get("first_air_date")),
        runtime_min=minutes(runtimes[0] if runtimes else None), overview=plain_text(s.get("overview")),
        poster_url=_img(s.get("poster_path")),
        ext_ids=ids(tmdb=s.get("id"), imdb=ext.get("imdb_id"), tvdb=ext.get("tvdb_id"), wikidata=ext.get("wikidata_id")),
        extra={k: v for k, v in {
            "networks": [n.get("name") for n in s.get("networks") or [] if n.get("name")],
            "status": s.get("status"), "original_language": s.get("original_language"),
            "genres": [g.get("name") for g in s.get("genres") or [] if g.get("name")]}.items() if v},
    )


def _season(series_id, s: dict) -> Item:
    number = as_int(s.get("season_number"))
    return Item(
        kind="season", title=s.get("name") or f"Season {number}", position=number,
        year=year_of(s.get("air_date")), release_date=iso_date(s.get("air_date")),
        overview=plain_text(s.get("overview")), poster_url=_img(s.get("poster_path")),
        ext_ids={"tmdb": f"{series_id}/{number}"},
        extra={k: v for k, v in {"episode_count": s.get("episode_count") or len(s.get("episodes") or []),
                                 "tmdb_season": s.get("id")}.items() if v},
    )


def _episode(e: dict) -> Item:
    return Item(
        kind="episode", title=e.get("name") or "", position=as_int(e.get("episode_number")),
        year=year_of(e.get("air_date")), release_date=iso_date(e.get("air_date")),
        runtime_min=minutes(e.get("runtime")), overview=plain_text(e.get("overview")),
        poster_url=_img(e.get("still_path")), ext_ids=ids(tmdb=e.get("id")),
        extra={"season": e.get("season_number")} if e.get("season_number") is not None else {},
    )


def _person(p: dict) -> Person:
    return Person(name=p.get("name") or "", ext_ids=ids(tmdb=p.get("id")), image_url=_img(p.get("profile_path")))


def _cast_and_crew(block: dict) -> List[Credit]:
    out: List[Credit] = []
    for c in sorted(block.get("cast") or [], key=lambda c: c.get("order") if c.get("order") is not None else 9999):
        roles = c.get("roles") or [{"character": c.get("character")}]
        for r in roles:
            out.append(Credit(person=_person(c), role="actor", character=r.get("character") or ""))
    for c in block.get("crew") or []:
        for job in [j.get("job") for j in c.get("jobs") or []] or [c.get("job")]:
            role = normalise_role(job or c.get("department"))
            if role:
                out.append(Credit(person=_person(c), role=role))
    return out


class TMDBSource(CatalogSource):
    name = "tmdb"
    priority = 20
    lookup_kinds = {"movie": ("tmdb", "imdb"), "collection": ("tmdb",), "series": ("tmdb", "imdb"),
                    "season": ("tmdb",)}
    children_kinds = frozenset({"collection", "series", "season"})
    credits_kinds = {"movie": ("tmdb", "imdb"), "series": ("tmdb", "imdb")}
    person_schemes = ("tmdb", "imdb")

    def _get(self, path: str, timeout: float, **params) -> Optional[dict]:
        key = os.environ.get("TMDB_API_KEY", "")
        data = _http.get_json(f"{API}{path}", params={"api_key": key, **params}, timeout=timeout)
        return data if isinstance(data, dict) else None

    def _id(self, scheme: str, value: str, kind: str, timeout: float) -> Optional[str]:
        if scheme == "tmdb":
            return value if value.isdigit() else None
        found = self._get(f"/find/{value}", timeout, external_source="imdb_id") or {}
        bucket = {"movie": "movie_results", "series": "tv_results", "person": "person_results"}[kind]
        hit = next(iter(found.get(bucket) or []), None)
        return str(hit["id"]) if hit and hit.get("id") else None

    def lookup(self, scheme, value, kind, *, children, timeout):
        if kind == "season":
            series_id, _, number = value.partition("/")
            if not (series_id.isdigit() and number.isdigit()):
                return None
            s = self._get(f"/tv/{series_id}/season/{number}", timeout)
            if s is None:
                return None
            item = _season(series_id, s)
            if children:
                item.children = [_episode(e) for e in s.get("episodes") or []]
            return item
        if kind == "collection":
            c = self._get(f"/collection/{value}", timeout) if value.isdigit() else None
            if c is None:
                return None
            parts = sorted(c.get("parts") or [], key=lambda p: (p.get("release_date") or "9999"))
            item = Item(kind="collection", title=c.get("name") or "", overview=plain_text(c.get("overview")),
                        poster_url=_img(c.get("poster_path")), ext_ids=ids(tmdb=c.get("id")),
                        year=year_of(parts[0].get("release_date")) if parts else None)
            if children:
                item.children = [_movie(p, n) for n, p in enumerate(parts, 1)]
            return item
        tmdb_id = self._id(scheme, value, kind, timeout)
        if tmdb_id is None:
            return None
        if kind == "movie":
            m = self._get(f"/movie/{tmdb_id}", timeout, append_to_response="external_ids")
            return _movie(m) if m else None
        s = self._get(f"/tv/{tmdb_id}", timeout, append_to_response="external_ids")
        if s is None:
            return None
        item = _series(s)
        if children:
            item.children = [_season(tmdb_id, x) for x in s.get("seasons") or []]
        return item

    def credits(self, scheme, value, kind, *, timeout):
        tmdb_id = self._id(scheme, value, kind, timeout)
        if tmdb_id is None:
            return None
        if kind == "movie":
            m = self._get(f"/movie/{tmdb_id}", timeout, append_to_response="credits")
            if m is None:
                return None
            out = _cast_and_crew(m.get("credits") or {})
            companies = m.get("production_companies") or []
        else:
            s = self._get(f"/tv/{tmdb_id}", timeout, append_to_response="aggregate_credits")
            if s is None:
                return None
            out = [Credit(person=_person(c), role="creator") for c in s.get("created_by") or []]
            out += _cast_and_crew(s.get("aggregate_credits") or {})
            out += [Credit(person=Person(name=n["name"], kind="company", ext_ids=ids(tmdb=n.get("id"))),
                           role="network") for n in s.get("networks") or [] if n.get("name")]
            companies = s.get("production_companies") or []
        out += [Credit(person=Person(name=c["name"], kind="company", ext_ids=ids(tmdb=c.get("id"))), role="studio")
                for c in companies if c.get("name")]
        return merge_credits(out)

    def person(self, scheme, value, *, timeout):
        tmdb_id = self._id(scheme, value, "person", timeout)
        if tmdb_id is None:
            return None
        p = self._get(f"/person/{tmdb_id}", timeout, append_to_response="combined_credits,external_ids")
        if p is None:
            return None
        ext = p.get("external_ids") or {}
        person = Person(
            name=p.get("name") or "", ext_ids=ids(tmdb=p.get("id"), imdb=p.get("imdb_id") or ext.get("imdb_id"),
                                                  wikidata=ext.get("wikidata_id")),
            aliases=[a for a in p.get("also_known_as") or [] if a], image_url=_img(p.get("profile_path")),
            birth_date=iso_date(p.get("birthday")), death_date=iso_date(p.get("deathday")),
            bio=plain_text(p.get("biography")),
            extra={k: v for k, v in {"place_of_birth": p.get("place_of_birth"),
                                     "known_for": p.get("known_for_department")}.items() if v},
        )
        me = Person(name=person.name, ext_ids=ids(tmdb=p.get("id")))
        combined = p.get("combined_credits") or {}
        credits: List[Credit] = []
        for c in combined.get("cast") or []:
            item = _movie(c) if c.get("media_type") == "movie" else _series(c)
            credits.append(Credit(person=me, role="actor", character=c.get("character") or "", item=item))
        for c in combined.get("crew") or []:
            role = normalise_role(c.get("job") or c.get("department"))
            if role:
                item = _movie(c) if c.get("media_type") == "movie" else _series(c)
                credits.append(Credit(person=me, role=role, item=item))
        return PersonDetails(person=person, credits=credits)


register_source(TMDBSource())
