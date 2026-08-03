"""TMDB TV series catalog crawler.

Paginates /discover/tv year-by-year (1920-current) to bypass the 10k limit.
Requires TMDB_API_KEY environment variable.

Same page-number-inside-year-loop pagination as :mod:`tmdb_movies`, so
:meth:`fetch` is overridden directly; the cursor is ``{"year": Y, "page": P}``.

Run it::

    TMDB_API_KEY=xxx python -m metadatarr.scrapers tmdb_tv [--output DIR] [--delay SECS]
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

BASE = "https://api.themoviedb.org/3"
START_YEAR = 1920
END_YEAR = datetime.now().year

_GENRE_MAP: Dict[int, str] = {
    10759: "Action & Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
    99: "Documentary", 18: "Drama", 10751: "Family", 10762: "Kids",
    9648: "Mystery", 10763: "News", 10764: "Reality", 10765: "Sci-Fi & Fantasy",
    10766: "Soap", 10767: "Talk", 10768: "War & Politics", 37: "Western",
}


@register
class TMDBTVSource(PaginatedJSONSource):
    name = "tmdb_tv"
    id_field = "tmdb_id"
    default_delay = 0.25

    base = f"{BASE}/discover/tv"
    results_key = "results"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self.api_key = os.environ.get("TMDB_API_KEY", "")

    def initial_cursor(self) -> Dict[str, int]:
        return {"year": START_YEAR, "page": 1}

    def map_row(self, s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not s.get("id"):
            return None
        genre_ids = s.get("genre_ids") or []
        return {
            "tmdb_id": s.get("id"),
            "name": s.get("name"),
            "original_name": s.get("original_name"),
            "original_language": s.get("original_language"),
            "first_air_date": s.get("first_air_date"),
            "origin_country": s.get("origin_country") or [],
            "genres": [_GENRE_MAP.get(g, str(g)) for g in genre_ids],
            "vote_average": s.get("vote_average"),
            "vote_count": s.get("vote_count"),
            "popularity": s.get("popularity"),
            "overview": (s.get("overview") or "")[:500],
            "poster_path": s.get("poster_path"),
            "entity_type": "tv_series",
        }

    def fetch(self, cursor: Dict[str, int]):
        year = int(cursor.get("year", START_YEAR))
        page = int(cursor.get("page", 1))
        if year > END_YEAR:
            return [], None

        params = {
            "api_key": self.api_key,
            "language": "en-US",
            "sort_by": "popularity.desc",
            "first_air_date_year": year,
            "page": page,
            "include_null_first_air_dates": "false",
        }
        data = self.get_json(self.base, params)
        total_pages = min(data.get("total_pages", 1), 500)
        shows: List[Dict[str, Any]] = data.get("results") or []

        rows = []
        for s in shows:
            row = self.map_row(s)
            if row is not None:
                rows.append(row)

        if not shows or page >= total_pages:
            next_year = year + 1
            next_cursor = {"year": next_year, "page": 1} if next_year <= END_YEAR else None
        else:
            next_cursor = {"year": year, "page": page + 1}
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(TMDBTVSource))
