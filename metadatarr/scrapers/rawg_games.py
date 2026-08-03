"""RAWG game database crawler.

Paginates the RAWG /games endpoint (500k+ games). Requires RAWG_KEY env var.
Free tier is very generous - no strict rate limit beyond basic politeness.

RAWG pages by a plain ``page`` number and signals the end via a ``next``
field rather than a short page, so :meth:`fetch` is overridden directly
(cursor is the page number).

Run it::

    RAWG_KEY=xxx python -m metadatarr.scrapers rawg_games [--output DIR] [--delay SECS]
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

BASE = "https://api.rawg.io/api"
PAGE_SIZE = 40


@register
class RAWGGamesSource(PaginatedJSONSource):
    name = "rawg_games"
    id_field = "rawg_id"
    default_delay = 0.5

    base = f"{BASE}/games"
    results_key = "results"
    page_size = PAGE_SIZE

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self.api_key = os.environ.get("RAWG_KEY", "")

    def initial_cursor(self) -> int:
        return 1

    def map_row(self, g: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not g.get("id"):
            return None
        genres = [x.get("name") for x in (g.get("genres") or []) if x.get("name")]
        platforms = [p.get("platform", {}).get("name") for p in (g.get("platforms") or [])
                     if p.get("platform", {}).get("name")]
        tags = [t.get("name") for t in (g.get("tags") or [])
                if t.get("name") and t.get("language") == "eng"]
        stores = [s.get("store", {}).get("name") for s in (g.get("stores") or [])
                  if s.get("store", {}).get("name")]
        return {
            "rawg_id": g.get("id"),
            "slug": g.get("slug"),
            "name": g.get("name"),
            "released": g.get("released"),
            "metacritic": g.get("metacritic"),
            "rating": g.get("rating"),
            "rating_top": g.get("rating_top"),
            "ratings_count": g.get("ratings_count"),
            "esrb_rating": (g.get("esrb_rating") or {}).get("name"),
            "genres": genres,
            "platforms": platforms,
            "tags": tags[:20],
            "stores": stores,
            "developers": [d.get("name") for d in (g.get("developers") or []) if d.get("name")],
            "publishers": [p.get("name") for p in (g.get("publishers") or []) if p.get("name")],
            "background_image": g.get("background_image"),
            "entity_type": "video_game",
        }

    def fetch(self, cursor: int):
        page = int(cursor)
        params = {
            "key": self.api_key,
            "page": page,
            "page_size": PAGE_SIZE,
            "ordering": "id",
        }
        data = self.get_json(self.base, params)
        results: List[Dict[str, Any]] = data.get("results") or []
        next_url = data.get("next")

        rows = []
        for g in results:
            row = self.map_row(g)
            if row is not None:
                rows.append(row)

        next_cursor = None if (not results or not next_url) else page + 1
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(RAWGGamesSource))
