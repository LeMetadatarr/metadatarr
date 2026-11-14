# SPDX-License-Identifier: Apache-2.0
"""AniList, keyless: anime details, characters with their voice actors, staff
and studios, and a staff member with their voice roles and staff roles.

AniList lists no episodes, so its anime lookups carry no children. Without a
kind from the caller, an anime is a movie or a series by its AniList format.
Characters, staff and a person's media are read page by page, up to
:data:`MAX_PAGES` pages of 25 and within the provider timeout; an answer cut
short reports ``truncated``. AniList allows 30 requests a minute, so requests
are spaced two seconds apart, and after a 429 no request is sent until its
Retry-After has passed."""
from __future__ import annotations

import re
import time
from typing import List, Optional

from metadatarr.catalog import _http
from metadatarr.catalog.base import CatalogSource, mark_truncated, register_source, report_partial_failure
from metadatarr.catalog.roles import normalise_role
from metadatarr.catalog.shapes import Credit, Item, Person, PersonDetails, merge_credits
from metadatarr.catalog.sources._util import ids, minutes, plain_text

API = "https://graphql.anilist.co"

_MEDIA_FIELDS = """id idMal format status episodes duration genres synonyms
 title { romaji english native } startDate { year month day } description(asHtml: false)
 coverImage { extraLarge large }"""

_LOOKUP = "query($id: Int, $idMal: Int) { Media(id: $id, idMal: $idMal, type: ANIME) { %s } }" % _MEDIA_FIELDS

# AniList answers at most 25 edges per page of a connection.
_PER_PAGE = 25
#: Pages read per connection; an answer cut there reports ``truncated``.
MAX_PAGES = 10

_CREDITS = """query($id: Int, $idMal: Int, $page: Int) { Media(id: $id, idMal: $idMal, type: ANIME) { id
 characters(sort: [ROLE, RELEVANCE], page: $page, perPage: %d) { pageInfo { hasNextPage }
   edges { role node { id name { full } } voiceActors { id name { full native alternative } image { large } languageV2 } } }
 staff(sort: RELEVANCE, page: $page, perPage: %d) { pageInfo { hasNextPage }
   edges { role node { id name { full native alternative } image { large } } } }
 studios { edges { isMain node { id name isAnimationStudio } } } } }""" % (_PER_PAGE, _PER_PAGE)

_PERSON = """query($id: Int, $page: Int) { Staff(id: $id) { id name { full native alternative } image { large }
 dateOfBirth { year month day } dateOfDeath { year month day } homeTown description(asHtml: false) languageV2
 characterMedia(page: $page, perPage: %d, sort: START_DATE_DESC) { pageInfo { hasNextPage }
   edges { characterRole node { %s } characters { name { full } } } }
 staffMedia(page: $page, perPage: %d, sort: START_DATE_DESC) { pageInfo { hasNextPage }
   edges { staffRole node { %s } } } } }""" % (_PER_PAGE, _MEDIA_FIELDS, _PER_PAGE, _MEDIA_FIELDS)

_NOTE = re.compile(r"\(([^)]*)\)")

_clock = time.monotonic
# Until when AniList asked not to be called (its Retry-After after a 429).
_BLOCKED_UNTIL = [0.0]


def _date(d: Optional[dict]) -> Optional[str]:
    d = d or {}
    if not d.get("year"):
        return None
    parts = [f"{d['year']:04d}"]
    if d.get("month"):
        parts.append(f"{d['month']:02d}")
        if d.get("day"):
            parts.append(f"{d['day']:02d}")
    return "-".join(parts)


def _media(m: dict, kind: Optional[str] = None) -> Item:
    title = m.get("title") or {}
    fmt = m.get("format") or ""
    kind = kind or ("movie" if fmt == "MOVIE" else "series")
    return Item(
        kind=kind, title=title.get("english") or title.get("romaji") or title.get("native") or "",
        original_title=title.get("native") or "", year=(m.get("startDate") or {}).get("year"),
        release_date=_date(m.get("startDate")), runtime_min=minutes(m.get("duration")),
        overview=plain_text(m.get("description")),
        poster_url=(m.get("coverImage") or {}).get("extraLarge") or (m.get("coverImage") or {}).get("large") or "",
        ext_ids=ids(anilist=m.get("id"), mal=m.get("idMal")),
        extra={k: v for k, v in {"format": fmt, "status": m.get("status"), "episodes": m.get("episodes"),
                                 "genres": m.get("genres") or [], "synonyms": m.get("synonyms") or [],
                                 "title_romaji": title.get("romaji")}.items() if v},
    )


def _staff(node: dict) -> Person:
    name = node.get("name") or {}
    aliases = [a for a in [name.get("native"), *(name.get("alternative") or [])] if a]
    return Person(name=name.get("full") or "", ext_ids=ids(anilist=node.get("id")), aliases=aliases,
                  image_url=(node.get("image") or {}).get("large") or "")


def _note(role: str) -> str:
    found = _NOTE.search(role or "")
    return found.group(1).strip() if found else ""


class AniListSource(CatalogSource):
    name = "anilist"
    priority = 10
    lookup_kinds = {"series": ("anilist", "mal"), "movie": ("anilist", "mal")}
    credits_kinds = {"series": ("anilist", "mal"), "movie": ("anilist", "mal")}
    person_schemes = ("anilist",)
    infers_kind = True

    @staticmethod
    def _variables(scheme: str, value: str) -> Optional[dict]:
        if not value.isdigit():
            return None
        return {"idMal": int(value)} if scheme == "mal" else {"id": int(value)}

    def _query(self, query: str, variables: dict, root: str, timeout: float) -> Optional[dict]:
        wait = _BLOCKED_UNTIL[0] - _clock()
        if wait > 0:
            raise _http.RateLimited(f"AniList asked for a pause; retry after {wait:.0f} s", wait)
        try:
            data = _http.post_json(API, {"query": query, "variables": variables}, timeout=timeout)
        except _http.RateLimited as e:
            if e.retry_after:
                _BLOCKED_UNTIL[0] = _clock() + e.retry_after
            raise
        if not isinstance(data, dict):
            return None
        if data.get("errors") and not (data.get("data") or {}).get(root):
            statuses = {e.get("status") for e in data["errors"] if isinstance(e, dict)}
            if statuses == {404}:
                return None
            raise _http.UpstreamError(f"AniList answered: {data['errors'][0].get('message')}")
        return (data.get("data") or {}).get(root)

    def _pages(self, query: str, variables: dict, root: str, connections: tuple,
               timeout: float) -> Optional[dict]:
        """The first page's root object with each connection's edges gathered
        over its pages; None when AniList does not know the id. Paging stops
        at :data:`MAX_PAGES` or once 60% of ``timeout`` has passed (the answer
        is then truncated and stays cacheable), or when a later page fails or
        is refused with 429 (truncated, and the failure is listed under the
        answer's errors, so it is not cached). Every request ends within 90%
        of ``timeout``."""
        start = time.monotonic()
        first: Optional[dict] = None
        for page in range(1, MAX_PAGES + 1):
            remaining = max(0.5, start + timeout * 0.9 - time.monotonic())
            try:
                data = self._query(query, {**variables, "page": page}, root, remaining)
            except Exception as e:
                if first is None:
                    raise
                report_partial_failure(e)
                return first
            if data is None:
                return first
            more = [c for c in connections if ((data.get(c) or {}).get("pageInfo") or {}).get("hasNextPage")]
            if first is None:
                first = data
                for c in connections:
                    first[c] = {"edges": list((data.get(c) or {}).get("edges") or [])}
            else:
                for c in connections:
                    first[c]["edges"].extend((data.get(c) or {}).get("edges") or [])
            if not more:
                return first
            if page == MAX_PAGES or time.monotonic() > start + timeout * 0.6:
                mark_truncated()
                return first
        return first

    def lookup(self, scheme, value, kind, *, children, timeout):
        variables = self._variables(scheme, value)
        m = variables and self._query(_LOOKUP, variables, "Media", timeout)
        return _media(m, kind) if m else None

    def credits(self, scheme, value, kind, *, timeout):
        variables = self._variables(scheme, value)
        m = variables and self._pages(_CREDITS, variables, "Media", ("characters", "staff"), timeout)
        if not m:
            return None
        out: List[Credit] = []
        for edge in (m.get("characters") or {}).get("edges") or []:
            character = ((edge.get("node") or {}).get("name") or {}).get("full") or ""
            for va in edge.get("voiceActors") or []:
                note = va.get("languageV2") or ""
                out.append(Credit(person=_staff(va), role="voice-actor", character=character, note=note))
        for edge in (m.get("staff") or {}).get("edges") or []:
            role = normalise_role(edge.get("role"))
            if role and edge.get("node"):
                out.append(Credit(person=_staff(edge["node"]), role=role, note=_note(edge.get("role"))))
        for edge in (m.get("studios") or {}).get("edges") or []:
            node = edge.get("node") or {}
            if node.get("name"):
                out.append(Credit(person=Person(name=node["name"], kind="company", ext_ids=ids(anilist=node.get("id"))),
                                  role="studio" if node.get("isAnimationStudio") else "producer",
                                  note="main" if edge.get("isMain") else ""))
        return merge_credits(out)

    def person(self, scheme, value, *, timeout):
        if not value.isdigit():
            return None
        s = self._pages(_PERSON, {"id": int(value)}, "Staff", ("characterMedia", "staffMedia"), timeout)
        if not s:
            return None
        person = _staff(s)
        person.birth_date, person.death_date = _date(s.get("dateOfBirth")), _date(s.get("dateOfDeath"))
        person.bio = plain_text(s.get("description"))
        person.extra = {k: v for k, v in {"home_town": s.get("homeTown"), "language": s.get("languageV2")}.items() if v}
        me = Person(name=person.name, ext_ids=person.ext_ids)
        credits: List[Credit] = []
        for edge in (s.get("characterMedia") or {}).get("edges") or []:
            if not edge.get("node"):
                continue
            item = _media(edge["node"])
            for ch in edge.get("characters") or [{}]:
                credits.append(Credit(person=me, role="voice-actor", item=item,
                                      character=((ch or {}).get("name") or {}).get("full") or ""))
        for edge in (s.get("staffMedia") or {}).get("edges") or []:
            role = normalise_role(edge.get("staffRole"))
            if role and edge.get("node"):
                credits.append(Credit(person=me, role=role, note=_note(edge.get("staffRole")), item=_media(edge["node"])))
        return PersonDetails(person=person, credits=credits)


register_source(AniListSource())
