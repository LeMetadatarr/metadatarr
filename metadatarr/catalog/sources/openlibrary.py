# SPDX-License-Identifier: Apache-2.0
"""Open Library, keyless: authors with their works, works (books) by work id,
edition id or ISBN, the authors and contributors of a book, and an author with
their works as a filmography.

A book is a work. A lookup by edition id or ISBN answers with the edition's
work: ``ext_ids`` keeps the work under ``openlibrary`` and the edition under
``openlibrary_edition``."""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Tuple

from metadatarr.catalog import _http
from metadatarr.catalog.base import CatalogSource, register_source
from metadatarr.catalog.roles import normalise_role
from metadatarr.catalog.shapes import Credit, Item, Person, PersonDetails, iso_date, merge_credits, year_of
from metadatarr.catalog.sources._util import ids, plain_text

API = "https://openlibrary.org"
COVERS = "https://covers.openlibrary.org"

_OLID = re.compile(r"^OL\d+[AWM]$", re.IGNORECASE)
_ISBN = re.compile(r"^(\d{9}[\dX]|\d{13})$", re.IGNORECASE)
_MAX_AUTHORS = 10
_REMOTE = {"wikidata": "wikidata", "goodreads": "goodreads", "imdb": "imdb", "musicbrainz": "musicbrainz",
           "librivox": "librivox"}


def _text(value) -> str:
    if isinstance(value, dict):
        value = value.get("value")
    return plain_text(value) if isinstance(value, str) else ""


def _date(text: Optional[str]) -> Optional[str]:
    """ISO form of an Open Library free-text date ("31 July 1965", "1965"), else the text as given."""
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%d %B %Y", "%B %d, %Y", "%Y-%m-%d", "%B %Y", "%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.strftime({"%B %Y": "%Y-%m", "%Y": "%Y"}.get(fmt, "%Y-%m-%d"))
    return iso_date(text) or text


def _key(path: Optional[str]) -> str:
    return (path or "").rstrip("/").rsplit("/", 1)[-1]


def _cover(covers, kind: str = "b") -> str:
    first = next((c for c in covers or [] if isinstance(c, int) and c > 0), None)
    return f"{COVERS}/{kind}/id/{first}-L.jpg" if first else ""


def _work_item(w: dict) -> Item:
    first = w.get("first_publish_date")
    return Item(
        kind="book", title=w.get("title") or "", year=year_of(_date(first)), release_date=_date(first),
        overview=_text(w.get("description")), poster_url=_cover(w.get("covers")),
        ext_ids=ids(openlibrary=_key(w.get("key"))),
        extra={k: v for k, v in {"subjects": (w.get("subjects") or [])[:20], "subtitle": w.get("subtitle")}.items() if v},
    )


def _author_person(a: dict) -> Person:
    ext = ids(openlibrary=_key(a.get("key")))
    for k, scheme in _REMOTE.items():
        if (a.get("remote_ids") or {}).get(k):
            ext.setdefault(scheme, str(a["remote_ids"][k]))
    return Person(
        name=a.get("name") or a.get("personal_name") or "", ext_ids=ext,
        aliases=sorted({n for n in a.get("alternate_names") or [] if n and n != a.get("name")}),
        image_url=_cover(a.get("photos"), "a"), birth_date=_date(a.get("birth_date")),
        death_date=_date(a.get("death_date")), bio=_text(a.get("bio")),
        extra={k: v for k, v in {"fuller_name": a.get("fuller_name")}.items() if v},
    )


class OpenLibrarySource(CatalogSource):
    name = "openlibrary"
    priority = 10
    lookup_kinds = {"author": ("openlibrary",), "book": ("openlibrary", "isbn")}
    children_kinds = frozenset({"author"})
    credits_kinds = {"book": ("openlibrary", "isbn")}
    person_schemes = ("openlibrary",)

    def _get(self, path: str, timeout: float, **params) -> Optional[dict]:
        data = _http.get_json(f"{API}{path}", params=params or None, timeout=timeout)
        return data if isinstance(data, dict) else None

    def _book(self, scheme: str, value: str, timeout: float) -> Tuple[Optional[dict], Optional[dict]]:
        """(work, edition) for a work id, an edition id or an ISBN."""
        value = value.replace("-", "").strip().upper() if scheme == "isbn" else value.strip().upper()
        if scheme == "isbn":
            if not _ISBN.match(value):
                return None, None
            edition = self._get(f"/isbn/{value}.json", timeout)
        elif _OLID.match(value) and value.endswith("M"):
            edition = self._get(f"/books/{value}.json", timeout)
        elif _OLID.match(value) and value.endswith("W"):
            return self._get(f"/works/{value}.json", timeout), None
        else:
            return None, None
        if edition is None:
            return None, None
        work_key = next((w.get("key") for w in edition.get("works") or [] if w.get("key")), None)
        work = self._get(f"{work_key}.json", timeout) if work_key else None
        return work or {"key": edition.get("key"), "title": edition.get("title")}, edition

    def _authors(self, keys: List[str], timeout: float) -> List[dict]:
        out = []
        for key in keys[:_MAX_AUTHORS]:
            a = self._get(f"/authors/{_key(key)}.json", timeout)
            if a:
                out.append(a)
        return out

    def lookup(self, scheme, value, kind, *, children, timeout):
        if kind == "author":
            value = value.upper()
            if not (_OLID.match(value) and value.endswith("A")):
                return None
            a = self._get(f"/authors/{value}.json", timeout)
            if a is None:
                return None
            person = _author_person(a)
            item = Item(kind="author", title=person.name, overview=person.bio, poster_url=person.image_url,
                        ext_ids=person.ext_ids,
                        extra={k: v for k, v in {"birth_date": person.birth_date,
                                                 "death_date": person.death_date}.items() if v})
            if children:
                works = self._get(f"/authors/{value}/works.json", timeout, limit=200) or {}
                item.children = [_work_item(w) for w in works.get("entries") or []]
            return item
        work, edition = self._book(scheme, value, timeout)
        if work is None:
            return None
        item = _work_item(work)
        if edition:
            item.ext_ids["openlibrary_edition"] = _key(edition.get("key"))
            item.extra["edition"] = ids(openlibrary=_key(edition.get("key")), publish_date=edition.get("publish_date"))
            if not item.poster_url:
                item.poster_url = _cover(edition.get("covers"))
            if scheme == "isbn":
                item.ext_ids["isbn"] = value.replace("-", "").upper()
        return item

    def credits(self, scheme, value, kind, *, timeout):
        work, edition = self._book(scheme, value, timeout)
        if work is None:
            return None
        keys = [(a.get("author") or {}).get("key") for a in work.get("authors") or []]
        keys = [k for k in keys if k] or [a.get("key") for a in (edition or {}).get("authors") or [] if a.get("key")]
        out = [Credit(person=_author_person(a), role="author") for a in self._authors(keys, timeout)]
        for c in (edition or {}).get("contributors") or []:
            role = normalise_role(c.get("role"))
            if c.get("name") and role:
                out.append(Credit(person=Person(name=c["name"]), role=role))
        for name in (edition or {}).get("publishers") or []:
            out.append(Credit(person=Person(name=name, kind="company"), role="publisher"))
        return merge_credits(out)

    def person(self, scheme, value, *, timeout):
        value = value.upper()
        if not (_OLID.match(value) and value.endswith("A")):
            return None
        a = self._get(f"/authors/{value}.json", timeout)
        if a is None:
            return None
        person = _author_person(a)
        me = Person(name=person.name, ext_ids=ids(openlibrary=value))
        works = self._get(f"/authors/{value}/works.json", timeout, limit=200) or {}
        credits = [Credit(person=me, role="author", item=_work_item(w)) for w in works.get("entries") or []]
        return PersonDetails(person=person, credits=credits)


register_source(OpenLibrarySource())
