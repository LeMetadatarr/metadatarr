"""Project Gutenberg catalog crawler via Gutendex.

Gutendex is a free, no-auth JSON API for the Project Gutenberg catalog
(~70k books). Pagination is an opaque ``next`` URL returned on every page
(not an offset), so the cursor is that URL itself and :meth:`fetch` is
overridden directly.

API: https://gutendex.com/

Run it::

    python -m metadatarr.scrapers gutenberg_books [--output DIR] [--limit N] [--delay SECS]
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

BASE = "https://gutendex.com/books/"


@register
class GutenbergBooksSource(PaginatedJSONSource):
    name = "gutenberg_books"
    id_field = "gutenberg_id"
    default_delay = 1.0

    base = BASE
    results_key = "results"

    def initial_cursor(self) -> str:
        return BASE

    def map_row(self, b: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        authors = []
        for a in (b.get("authors") or []):
            entry = {"name": a.get("name")}
            if a.get("birth_year"):
                entry["birth_year"] = a["birth_year"]
            if a.get("death_year"):
                entry["death_year"] = a["death_year"]
            authors.append(entry)

        translators = [a.get("name") for a in (b.get("translators") or []) if a.get("name")]

        formats = b.get("formats") or {}
        has_text = any("text/plain" in k or "text/html" in k for k in formats)
        has_epub = any("epub" in k for k in formats)

        return {
            "gutenberg_id": b.get("id"),
            "title": b.get("title"),
            "authors": authors,
            "translators": translators,
            "subjects": (b.get("subjects") or [])[:30],
            "bookshelves": (b.get("bookshelves") or [])[:15],
            "languages": b.get("languages") or [],
            "copyright": b.get("copyright"),
            "media_type": b.get("media_type"),
            "download_count": b.get("download_count"),
            "has_text": has_text,
            "has_epub": has_epub,
            "entity_type": "book",
        }

    def fetch(self, cursor: str):
        url = cursor or BASE
        data = self.get_json(url, None)
        books = data.get("results") or []
        next_url = data.get("next")

        if not books:
            return [], None

        rows = []
        for b in books:
            row = self.map_row(b)
            if row is not None:
                rows.append(row)

        return rows, next_url


if __name__ == "__main__":
    raise SystemExit(run_cli(GutenbergBooksSource))
