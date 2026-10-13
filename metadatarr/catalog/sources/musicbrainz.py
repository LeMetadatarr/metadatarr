# SPDX-License-Identifier: Apache-2.0
"""MusicBrainz, keyless (one request a second): artists with their release
groups, albums (release groups) with the tracks of one release, recordings,
the credits of an album or a recording, and an artist with their release
groups as a filmography.

An album is a release group. A lookup of kind ``album`` also takes a release
id; the tracks come from that release, or, for a release group, from its
earliest official release. Track positions count on across discs; the disc
and the place on it are in ``extra``.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from metadatarr.catalog import _http
from metadatarr.catalog.base import CatalogSource, register_source
from metadatarr.catalog.roles import normalise_role
from metadatarr.catalog.shapes import Credit, Item, Person, PersonDetails, iso_date, merge_credits, year_of
from metadatarr.catalog.sources._util import as_int, ids, minutes
from metadatarr.catalog.sources.skyhook import numbered_tracks

API = "https://musicbrainz.org/ws/2"
_MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

# MusicBrainz relationship types whose meaning is narrower than the generic word.
ROLE_OVERRIDES: Dict[str, str] = {
    "producer": "producer-music", "instrument": "performer", "vocal": "performer", "performer": "performer",
    "performing orchestra": "performer", "chorus master": "conductor", "mix": "mixer",
    "design": "cover-artist", "graphic design": "cover-artist", "artwork": "cover-artist",
}

# MusicBrainz artist types that name a group of people.
_GROUP_TYPES = {"group", "orchestra", "choir"}


def _kind(artist: dict) -> str:
    return "group" if (artist.get("type") or "").lower() in _GROUP_TYPES else "person"


def _artist_person(a: dict) -> Person:
    return Person(name=a.get("name") or "", kind=_kind(a), sort_name=a.get("sort-name") or "",
                  ext_ids=ids(musicbrainz=a.get("id")), country=a.get("country") or "")


def _artist_credits(credit: List[dict]) -> List[Credit]:
    """The artist credit of a release or recording: the first name is the
    artist, names joined by "feat." and the like are featured artists."""
    out: List[Credit] = []
    featured = False
    for part in credit or []:
        artist = part.get("artist") or {}
        if not (part.get("name") or artist.get("name")):
            continue
        person = _artist_person(artist)
        person.name = artist.get("name") or part.get("name")
        note = f"as {part['name']}" if part.get("name") and part.get("name") != person.name else ""
        out.append(Credit(person=person, role="featured-artist" if featured else "artist", note=note))
        joiner = (part.get("joinphrase") or "").lower()
        if any(w in joiner for w in ("feat", " ft", "with")):
            featured = True
    return out


def _relation_credits(relations: List[dict]) -> List[Credit]:
    out: List[Credit] = []
    for rel in relations or []:
        if rel.get("target-type") != "artist" or not rel.get("artist"):
            continue
        role = normalise_role(rel.get("type"), ROLE_OVERRIDES)
        if not role:
            continue
        attributes = [a for a in rel.get("attributes") or [] if a]
        note = ", ".join(attributes)
        if rel.get("type") == "vocal" and not note:
            note = "vocals"
        out.append(Credit(person=_artist_person(rel["artist"]), role=role, note=note))
    return out


def _release_group_item(rg: dict) -> Item:
    return Item(
        kind="album", title=rg.get("title") or "", year=year_of(rg.get("first-release-date")),
        release_date=iso_date(rg.get("first-release-date")), ext_ids=ids(musicbrainz=rg.get("id")),
        extra={k: v for k, v in {"type": rg.get("primary-type"), "secondary_types": rg.get("secondary-types") or [],
                                 "disambiguation": rg.get("disambiguation")}.items() if v},
    )


def _tracks(release: dict) -> List[Item]:
    """Tracks of every disc in order, positions counting on across discs."""
    out: List[Item] = []
    for medium in sorted(release.get("media") or [], key=lambda m: m.get("position") or 0):
        for t in sorted(medium.get("tracks") or [], key=lambda t: t.get("position") or 0):
            rec = t.get("recording") or {}
            out.append(Item(
                kind="track", title=t.get("title") or rec.get("title") or "",
                runtime_min=minutes(t.get("length") or rec.get("length"), 1 / 60000),
                ext_ids=ids(musicbrainz=rec.get("id")),
                extra={k: v for k, v in {"medium": medium.get("position") or 1,
                                         "disc_position": as_int(t.get("position")), "number": t.get("number"),
                                         "musicbrainz_track": t.get("id")}.items() if v},
            ))
    return numbered_tracks(out)


class MusicBrainzSource(CatalogSource):
    name = "musicbrainz"
    priority = 30
    lookup_kinds = {"artist": ("musicbrainz",), "album": ("musicbrainz",), "track": ("musicbrainz",)}
    children_kinds = frozenset({"artist", "album"})
    credits_kinds = {"album": ("musicbrainz",), "track": ("musicbrainz",)}
    person_schemes = ("musicbrainz",)

    def _get(self, path: str, timeout: float, **params) -> Optional[dict]:
        if not _MBID.match(path.rsplit("/", 1)[-1]) and "/" in path:
            return None
        data = _http.get_json(f"{API}/{path}", params={**params, "fmt": "json"}, timeout=timeout)
        return data if isinstance(data, dict) else None

    def _release_groups(self, artist_id: str, timeout: float) -> List[dict]:
        data = self._get("release-group", timeout, artist=artist_id, limit=100) or {}
        return data.get("release-groups") or []

    def _release(self, release_id: str, timeout: float, inc: str) -> Optional[dict]:
        return self._get(f"release/{release_id}", timeout, inc=inc)

    @staticmethod
    def _pick_release(releases: List[dict]) -> Optional[dict]:
        official = [r for r in releases if (r.get("status") or "").lower() == "official"] or releases
        return min(official, key=lambda r: r.get("date") or "9999", default=None)

    def _album(self, value: str, timeout: float):
        """(item, release id) for a release-group id or a release id."""
        rg = self._get(f"release-group/{value}", timeout, inc="releases+artist-credits")
        if rg is not None:
            item = _release_group_item(rg)
            artists = _artist_credits(rg.get("artist-credit") or [])
            if artists:
                item.extra["artist"] = {"name": artists[0].person.name, **artists[0].person.ext_ids}
            release = self._pick_release(rg.get("releases") or [])
            return item, (release or {}).get("id")
        release = self._release(value, timeout, "release-groups+artist-credits")
        if release is None:
            return None, None
        group = release.get("release-group") or {}
        item = _release_group_item({**group, "title": release.get("title") or group.get("title")})
        item.ext_ids = ids(musicbrainz=group.get("id") or release.get("id"))
        return item, release.get("id")

    def lookup(self, scheme, value, kind, *, children, timeout):
        if kind == "artist":
            a = self._get(f"artist/{value}", timeout, inc="aliases")
            if a is None:
                return None
            item = Item(kind="artist", title=a.get("name") or "", sort_title=a.get("sort-name") or "",
                        ext_ids=ids(musicbrainz=a.get("id")),
                        extra={k: v for k, v in {"type": a.get("type"), "country": a.get("country"),
                                                 "disambiguation": a.get("disambiguation")}.items() if v})
            if children:
                groups = sorted(self._release_groups(value, timeout),
                                key=lambda g: (g.get("first-release-date") or "9999", g.get("title") or ""))
                item.children = [_release_group_item(g) for g in groups]
            return item
        if kind == "album":
            item, release_id = self._album(value, timeout)
            if item is None:
                return None
            if release_id:
                item.extra["release"] = {"musicbrainz": release_id}
                if children:
                    release = self._release(release_id, timeout, "recordings")
                    item.children = _tracks(release or {})
            return item
        if kind == "track":
            rec = self._get(f"recording/{value}", timeout, inc="artist-credits")
            if rec is None:
                return None
            artists = _artist_credits(rec.get("artist-credit") or [])
            return Item(kind="track", title=rec.get("title") or "", year=year_of(rec.get("first-release-date")),
                        release_date=iso_date(rec.get("first-release-date")),
                        runtime_min=minutes(rec.get("length"), 1 / 60000), ext_ids=ids(musicbrainz=rec.get("id")),
                        extra={"artist": {"name": artists[0].person.name, **artists[0].person.ext_ids}}
                        if artists else {})
        return None

    def credits(self, scheme, value, kind, *, timeout):
        if kind == "album":
            item, release_id = self._album(value, timeout)
            if item is None or not release_id:
                return None if item is None else []
            release = self._release(release_id, timeout, "artist-credits+labels+artist-rels") or {}
            out = _artist_credits(release.get("artist-credit") or [])
            out += _relation_credits(release.get("relations") or [])
            for info in release.get("label-info") or []:
                label = info.get("label") or {}
                if label.get("name"):
                    out.append(Credit(person=Person(name=label["name"], kind="company",
                                                    ext_ids=ids(musicbrainz=label.get("id"))),
                                      role="label", note=info.get("catalog-number") or ""))
            return merge_credits(out)
        if kind == "track":
            rec = self._get(f"recording/{value}", timeout, inc="artist-credits+artist-rels+work-rels+work-level-rels")
            if rec is None:
                return None
            out = _artist_credits(rec.get("artist-credit") or [])
            out += _relation_credits(rec.get("relations") or [])
            for rel in rec.get("relations") or []:
                if rel.get("target-type") == "work":
                    out += _relation_credits((rel.get("work") or {}).get("relations") or [])
            return merge_credits(out)
        return None

    def person(self, scheme, value, *, timeout):
        a = self._get(f"artist/{value}", timeout, inc="aliases+url-rels")
        if a is None:
            return None
        span = a.get("life-span") or {}
        group = _kind(a) == "group"
        extra = {k: v for k, v in {"type": a.get("type"), "disambiguation": a.get("disambiguation"),
                                   "gender": a.get("gender")}.items() if v}
        if group:
            extra.update({k: v for k, v in {"formed": span.get("begin"), "disbanded": span.get("end")}.items() if v})
        ext = ids(musicbrainz=a.get("id"))
        for rel in a.get("relations") or []:
            url = ((rel.get("url") or {}).get("resource") or "").rstrip("/")
            if rel.get("type") == "wikidata" and url:
                ext.setdefault("wikidata", url.rsplit("/", 1)[-1])
            elif rel.get("type") == "discogs" and "/artist/" in url:
                ext.setdefault("discogs", url.rsplit("/", 1)[-1])
        person = Person(
            name=a.get("name") or "", kind=_kind(a), sort_name=a.get("sort-name") or "", ext_ids=ext,
            aliases=sorted({al["name"] for al in a.get("aliases") or [] if al.get("name")}),
            birth_date=None if group else iso_date(span.get("begin")),
            death_date=None if group else iso_date(span.get("end")),
            country=a.get("country") or "", extra=extra,
        )
        me = Person(name=person.name, kind=person.kind, ext_ids=ids(musicbrainz=a.get("id")))
        credits = [Credit(person=me, role="artist", item=_release_group_item(g))
                   for g in sorted(self._release_groups(value, timeout),
                                   key=lambda g: (g.get("first-release-date") or "9999", g.get("title") or ""))]
        return PersonDetails(person=person, credits=credits)


register_source(MusicBrainzSource())
