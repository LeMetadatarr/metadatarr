# SPDX-License-Identifier: Apache-2.0
"""LibriVox, keyless: an audiobook with its chapters, and its authors,
translators and readers (narrators, with the chapters each one read).

LibriVox numbers authors and readers separately, so a person carries
``librivox_author`` or ``librivox_reader``, never the book's ``librivox``."""
from __future__ import annotations

from typing import Dict, List

from metadatarr.catalog import _http
from metadatarr.catalog.base import CatalogSource, register_source
from metadatarr.catalog.shapes import Credit, Item, Person, merge_credits
from metadatarr.catalog.sources._util import as_int, ids, minutes, plain_text

API = "https://librivox.org/api/feed/audiobooks/"  # the trailing slash is required


def _name(a: dict) -> str:
    return f"{a.get('first_name') or ''} {a.get('last_name') or ''}".strip()


def _ranges(numbers: List[int]) -> str:
    """"1-3, 7" from [1, 2, 3, 7]."""
    numbers = sorted(set(numbers))
    out, start = [], None
    for i, n in enumerate(numbers):
        if start is None:
            start = n
        if i + 1 == len(numbers) or numbers[i + 1] != n + 1:
            out.append(str(start) if start == n else f"{start}-{n}")
            start = None
    return ", ".join(out)


class LibriVoxSource(CatalogSource):
    name = "librivox"
    priority = 10
    lookup_kinds = {"audiobook": ("librivox",)}
    children_kinds = frozenset({"audiobook"})
    credits_kinds = {"audiobook": ("librivox",)}

    def _book(self, value: str, timeout: float):
        if not value.isdigit():
            return None
        data = _http.get_json(API, params={"id": value, "format": "json", "extended": "1"}, timeout=timeout)
        books = (data or {}).get("books") if isinstance(data, dict) else None
        return next((b for b in books or [] if str(b.get("id")) == value), None)

    def lookup(self, scheme, value, kind, *, children, timeout):
        b = self._book(value, timeout)
        if b is None:
            return None
        item = Item(
            kind="audiobook", title=(b.get("title") or "").strip(), overview=plain_text(b.get("description")),
            runtime_min=minutes(b.get("totaltimesecs"), 1 / 60), ext_ids=ids(librivox=b.get("id")),
            extra={k: v for k, v in {
                "language": b.get("language"), "copyright_year": b.get("copyright_year"),
                "url_librivox": b.get("url_librivox"), "url_rss": b.get("url_rss"),
                "url_iarchive": b.get("url_iarchive"), "url_text_source": b.get("url_text_source"),
                "genres": [g.get("name") for g in b.get("genres") or [] if g.get("name")],
                "authors": [_name(a) for a in b.get("authors") or [] if _name(a)]}.items() if v},
        )
        if children:
            for s in sorted(b.get("sections") or [], key=lambda s: as_int(s.get("section_number")) or 0):
                item.children.append(Item(
                    kind="chapter", title=(s.get("title") or "").strip(), position=as_int(s.get("section_number")),
                    runtime_min=minutes(s.get("playtime"), 1 / 60),
                    extra={k: v for k, v in {
                        "librivox_section": s.get("id"), "listen_url": s.get("listen_url"),
                        "readers": [r.get("display_name") for r in s.get("readers") or [] if r.get("display_name")],
                    }.items() if v},
                ))
        return item

    def credits(self, scheme, value, kind, *, timeout):
        b = self._book(value, timeout)
        if b is None:
            return None
        out: List[Credit] = []
        for a in b.get("authors") or []:
            if _name(a):
                out.append(Credit(person=Person(name=_name(a), ext_ids=ids(librivox_author=a.get("id")),
                                                birth_date=a.get("dob") or None, death_date=a.get("dod") or None),
                                  role="author"))
        for t in b.get("translators") or []:
            if _name(t):
                out.append(Credit(person=Person(name=_name(t), ext_ids=ids(librivox_author=t.get("id"))), role="translator"))
        chapters: Dict[str, List[int]] = {}
        names: Dict[str, str] = {}
        for s in b.get("sections") or []:
            for r in s.get("readers") or []:
                rid = str(r.get("reader_id") or r.get("display_name") or "")
                if rid and r.get("display_name"):
                    names.setdefault(rid, r["display_name"])
                    chapters.setdefault(rid, []).append(as_int(s.get("section_number")) or 0)
        for rid, numbers in chapters.items():
            out.append(Credit(person=Person(name=names[rid], ext_ids=ids(librivox_reader=rid) if rid.isdigit() else {}),
                              role="narrator", note=f"chapters {_ranges(numbers)}"))
        return merge_credits(out)


register_source(LibriVoxSource())
