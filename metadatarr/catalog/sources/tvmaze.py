# SPDX-License-Identifier: Apache-2.0
"""TVmaze, keyless: series with seasons, seasons with episodes, cast and crew,
and people with their cast and crew credits."""
from __future__ import annotations

from typing import List, Optional

from metadatarr.catalog import _http
from metadatarr.catalog.base import CatalogSource, register_source
from metadatarr.catalog.roles import normalise_role
from metadatarr.catalog.shapes import Credit, Item, Person, PersonDetails, iso_date, merge_credits, year_of
from metadatarr.catalog.sources._util import as_int, ids, minutes, plain_text

API = "https://api.tvmaze.com"


def _image(obj: Optional[dict]) -> str:
    img = (obj or {}).get("image") or {}
    return img.get("original") or img.get("medium") or ""


def _show(s: dict) -> Item:
    ext = s.get("externals") or {}
    channel = (s.get("network") or s.get("webChannel") or {}).get("name")
    return Item(
        kind="series", title=s.get("name") or "", year=year_of(s.get("premiered")),
        release_date=iso_date(s.get("premiered")), runtime_min=minutes(s.get("averageRuntime") or s.get("runtime")),
        overview=plain_text(s.get("summary")), poster_url=_image(s),
        ext_ids=ids(tvmaze=s.get("id"), tvdb=ext.get("thetvdb"), imdb=ext.get("imdb")),
        extra={k: v for k, v in {"network": channel, "status": s.get("status"), "type": s.get("type"),
                                 "language": s.get("language"), "genres": s.get("genres") or []}.items() if v},
    )


def _season(s: dict) -> Item:
    number = as_int(s.get("number"))
    return Item(
        kind="season", title=s.get("name") or (f"Season {number}" if number is not None else "Season"),
        position=number, year=year_of(s.get("premiereDate")), release_date=iso_date(s.get("premiereDate")),
        overview=plain_text(s.get("summary")), poster_url=_image(s), ext_ids=ids(tvmaze=s.get("id")),
        extra={k: v for k, v in {"episode_order": s.get("episodeOrder")}.items() if v},
    )


def _episode(e: dict) -> Item:
    return Item(
        kind="episode", title=e.get("name") or "", position=as_int(e.get("number")),
        year=year_of(e.get("airdate")), release_date=iso_date(e.get("airdate")),
        runtime_min=minutes(e.get("runtime")), overview=plain_text(e.get("summary")), poster_url=_image(e),
        ext_ids=ids(tvmaze=e.get("id")),
        extra={k: v for k, v in {"season": e.get("season"), "type": e.get("type")}.items() if v is not None},
    )


def _person(p: dict) -> Person:
    return Person(
        name=p.get("name") or "", ext_ids=ids(tvmaze=p.get("id")), image_url=_image(p),
        birth_date=iso_date(p.get("birthday")), death_date=iso_date(p.get("deathday")),
        country=((p.get("country") or {}).get("code") or ""),
        extra={k: v for k, v in {"gender": p.get("gender")}.items() if v},
    )


def _cast_role(c: dict) -> str:
    if c.get("voice"):
        return "voice-actor"
    if c.get("self"):
        return "self"
    return "actor"


class TVmazeSource(CatalogSource):
    name = "tvmaze"
    priority = 30
    lookup_kinds = {"series": ("tvmaze", "tvdb", "imdb"), "season": ("tvmaze",)}
    children_kinds = frozenset({"series", "season"})
    credits_kinds = {"series": ("tvmaze", "tvdb", "imdb")}
    person_schemes = ("tvmaze",)

    def _show_id(self, scheme: str, value: str, timeout: float) -> Optional[str]:
        if scheme == "tvmaze":
            return value if value.isdigit() else None
        param = {"tvdb": "thetvdb", "imdb": "imdb"}[scheme]
        found = _http.get_json(f"{API}/lookup/shows", params={param: value}, timeout=timeout)
        return str(found["id"]) if isinstance(found, dict) and found.get("id") else None

    def _get_show(self, scheme, value, timeout, embed) -> Optional[dict]:
        sid = self._show_id(scheme, value, timeout)
        if sid is None:
            return None
        params = {"embed[]": list(embed)} if embed else None
        s = _http.get_json(f"{API}/shows/{sid}", params=params, timeout=timeout)
        return s if isinstance(s, dict) and s.get("id") else None

    def lookup(self, scheme, value, kind, *, children, timeout):
        if kind == "series":
            s = self._get_show(scheme, value, timeout, ("seasons",) if children else ())
            if not s:
                return None
            item = _show(s)
            if children:
                item.children = [_season(x) for x in (s.get("_embedded") or {}).get("seasons") or []]
            return item
        if kind == "season":
            if not value.isdigit():
                return None
            s = _http.get_json(f"{API}/seasons/{value}", timeout=timeout)
            if not isinstance(s, dict) or not s.get("id"):
                return None
            item = _season(s)
            if children:
                eps = _http.get_json(f"{API}/seasons/{value}/episodes", timeout=timeout) or []
                item.children = [_episode(e) for e in eps if isinstance(e, dict)]
            return item
        return None

    def credits(self, scheme, value, kind, *, timeout):
        s = self._get_show(scheme, value, timeout, ("cast", "crew"))
        if not s:
            return None
        embedded = s.get("_embedded") or {}
        out: List[Credit] = []
        for c in embedded.get("cast") or []:
            p = c.get("person") or {}
            if p.get("name"):
                out.append(Credit(person=_person(p), role=_cast_role(c),
                                  character=(c.get("character") or {}).get("name") or ""))
        for c in embedded.get("crew") or []:
            p = c.get("person") or {}
            role = normalise_role(c.get("type"))
            if p.get("name") and role:
                out.append(Credit(person=_person(p), role=role))
        channel = (s.get("network") or s.get("webChannel") or {}).get("name")
        if channel:
            out.append(Credit(person=Person(name=channel, kind="company"), role="network"))
        return merge_credits(out)

    def person(self, scheme, value, *, timeout):
        if not value.isdigit():
            return None
        p = _http.get_json(f"{API}/people/{value}", timeout=timeout)
        if not isinstance(p, dict) or not p.get("id"):
            return None
        me = Person(name=p.get("name") or "", ext_ids=ids(tvmaze=p.get("id")))
        out: List[Credit] = []
        cast = _http.get_json(f"{API}/people/{value}/castcredits",
                              params={"embed[]": ["show", "character"]}, timeout=timeout) or []
        for c in cast:
            emb = c.get("_embedded") or {}
            if emb.get("show"):
                out.append(Credit(person=me, role=_cast_role(c),
                                  character=(emb.get("character") or {}).get("name") or "",
                                  item=_show(emb["show"])))
        crew = _http.get_json(f"{API}/people/{value}/crewcredits", params={"embed": "show"}, timeout=timeout) or []
        for c in crew:
            emb = c.get("_embedded") or {}
            role = normalise_role(c.get("type"))
            if emb.get("show") and role:
                out.append(Credit(person=me, role=role, item=_show(emb["show"])))
        return PersonDetails(person=_person(p), credits=out)


register_source(TVmazeSource())
