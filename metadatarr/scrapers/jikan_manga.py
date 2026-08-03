"""Jikan (MyAnimeList) manga crawler.

Uses the Jikan v4 REST API (no key required, rate-limit ~3 req/s). Covers
manga, manhwa, manhua, light novels, and doujinshi.

Jikan pages by a plain ``page`` number and signals the end via
``pagination.has_next_page`` rather than a short page, so :meth:`fetch` is
overridden directly (cursor is the page number).

Run it::

    python -m metadatarr.scrapers jikan_manga [--output DIR] [--limit N] [--delay SECS]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

BASE_URL = "https://api.jikan.moe/v4/manga"
PAGE_SIZE = 25  # Jikan max


@register
class JikanMangaSource(PaginatedJSONSource):
    name = "jikan_manga"
    id_field = "mal_id"
    default_delay = 0.4

    base = BASE_URL
    results_key = "data"
    page_size = PAGE_SIZE

    def initial_cursor(self) -> int:
        return 1

    def map_row(self, m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if m.get("mal_id") is None:
            return None

        pub = m.get("published") or {}
        prop = pub.get("prop") or {}
        from_prop = prop.get("from") or {}
        to_prop = prop.get("to") or {}

        def _date(p: Dict) -> Optional[str]:
            y = p.get("year")
            mo = p.get("month")
            d = p.get("day")
            if y:
                parts = [str(y)]
                if mo:
                    parts.append(f"{mo:02d}")
                    if d:
                        parts.append(f"{d:02d}")
                return "-".join(parts)
            return None

        titles = m.get("titles") or []
        aliases = [t.get("title") for t in titles if t.get("title") and t.get("type") not in ("Default",)]

        authors = [
            a.get("name") for a in (m.get("authors") or []) if a.get("name")
        ]
        serializations = [
            s.get("name") for s in (m.get("serializations") or []) if s.get("name")
        ]
        genres = [g.get("name") for g in (m.get("genres") or []) if g.get("name")]
        themes = [t.get("name") for t in (m.get("themes") or []) if t.get("name")]
        demographics = [d.get("name") for d in (m.get("demographics") or []) if d.get("name")]

        return {
            "mal_id": m.get("mal_id"),
            "title": m.get("title"),
            "title_english": m.get("title_english"),
            "title_japanese": m.get("title_japanese"),
            "aliases": aliases,
            "type": m.get("type"),
            "status": m.get("status"),
            "chapters": m.get("chapters"),
            "volumes": m.get("volumes"),
            "published_from": _date(from_prop),
            "published_to": _date(to_prop),
            "authors": authors,
            "serializations": serializations,
            "genres": genres,
            "themes": themes,
            "demographics": demographics,
            "score": m.get("score"),
            "scored_by": m.get("scored_by"),
            "rank": m.get("rank"),
            "popularity": m.get("popularity"),
            "members": m.get("members"),
            "synopsis": (m.get("synopsis") or "")[:500] or None,
            "background": (m.get("background") or "")[:300] or None,
            "approved": m.get("approved"),
        }

    def fetch(self, cursor: int):
        page = int(cursor)
        data = self.get_json(self.base, {
            "page": page, "limit": PAGE_SIZE, "order_by": "mal_id", "sort": "asc",
        })
        items: List[Dict[str, Any]] = data.get("data") or []
        pagination = data.get("pagination") or {}

        if not items:
            return [], None

        rows = []
        for m in items:
            row = self.map_row(m)
            if row is not None:
                rows.append(row)

        next_cursor = page + 1 if pagination.get("has_next_page", True) else None
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(JikanMangaSource))
