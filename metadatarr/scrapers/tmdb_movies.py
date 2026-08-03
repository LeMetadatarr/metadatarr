"""TMDB movie catalog crawler.

Paginates /discover/movie year-by-year (1888-current) to bypass the 10k
/discover result cap. Requires TMDB_API_KEY environment variable.

Pagination doesn't fit the engine's offset/skip model: TMDB pages by a plain
``page`` number (fixed 20 results/page, server-controlled) nested inside a
year loop, so :meth:`fetch` is overridden directly; the cursor is
``{"year": Y, "page": P}``.

Run it::

    TMDB_API_KEY=xxx python -m metadatarr.scrapers tmdb_movies [--output DIR] [--delay SECS]
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

BASE = "https://api.themoviedb.org/3"
START_YEAR = 1888
END_YEAR = datetime.now().year

# Map numeric genre IDs returned by /discover -> names (stable TMDB list)
_GENRE_MAP: Dict[int, str] = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
    99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
    27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance",
    878: "Science Fiction", 10770: "TV Movie", 53: "Thriller",
    10752: "War", 37: "Western",
}


@register
class TMDBMoviesSource(PaginatedJSONSource):
    name = "tmdb_movies"
    id_field = "tmdb_id"
    default_delay = 0.25

    base = f"{BASE}/discover/movie"
    results_key = "results"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self.api_key = os.environ.get("TMDB_API_KEY", "")

    def initial_cursor(self) -> Dict[str, int]:
        return {"year": START_YEAR, "page": 1}

    def map_row(self, m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not m.get("id"):
            return None
        genre_ids = m.get("genre_ids") or []
        return {
            "tmdb_id": m.get("id"),
            "title": m.get("title"),
            "original_title": m.get("original_title"),
            "original_language": m.get("original_language"),
            "release_date": m.get("release_date"),
            "genres": [_GENRE_MAP.get(g, str(g)) for g in genre_ids],
            "vote_average": m.get("vote_average"),
            "vote_count": m.get("vote_count"),
            "popularity": m.get("popularity"),
            "adult": m.get("adult", False),
            "overview": (m.get("overview") or "")[:500],
            "poster_path": m.get("poster_path"),
            "entity_type": "film",
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
            "primary_release_year": year,
            "page": page,
            "include_adult": "false",
        }
        data = self.get_json(self.base, params)
        total_pages = min(data.get("total_pages", 1), 500)
        movies: List[Dict[str, Any]] = data.get("results") or []

        rows = []
        for m in movies:
            row = self.map_row(m)
            if row is not None:
                rows.append(row)

        if not movies or page >= total_pages:
            next_year = year + 1
            next_cursor = {"year": next_year, "page": 1} if next_year <= END_YEAR else None
        else:
            next_cursor = {"year": year, "page": page + 1}
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(TMDBMoviesSource))
