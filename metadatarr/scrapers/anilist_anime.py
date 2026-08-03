"""AniList anime (and manga) GraphQL crawler.

Paginates the full AniList catalog via their public GraphQL endpoint. No API
key required. Covers both ANIME and MANGA media types via ``--type``
(default ``ANIME``; ``ALL`` walks both, one after the other).

AniList pagination is GraphQL page/perPage with a ``pageInfo.hasNextPage``
end signal, and the engine's shared ``get_json`` is GET-only, so
:meth:`fetch` posts the query directly and reproduces the original's 429
(rate-limit, sleep + retry) and 400 (past-last-page, treat as complete)
handling. The cursor is ``{"type_idx": i, "page": P}``, walking
``self.media_types`` (set from ``--type`` in :meth:`configure`).

Run it::

    python -m metadatarr.scrapers anilist_anime [--output DIR] [--limit N] [--delay SECS]
                                                 [--type {ANIME,MANGA,ALL}]
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

GRAPHQL_URL = "https://graphql.anilist.co"
PAGE_SIZE = 50  # AniList max is 50 per page

_QUERY = """
query ($page: Int, $perPage: Int, $type: MediaType) {
  Page(page: $page, perPage: $perPage) {
    pageInfo {
      hasNextPage
      currentPage
      lastPage
      total
    }
    media(type: $type, sort: ID) {
      id
      idMal
      title { romaji english native }
      type
      format
      status
      episodes
      duration
      chapters
      volumes
      countryOfOrigin
      source
      startDate { year month day }
      endDate { year month day }
      season
      seasonYear
      genres
      tags { name category isAdult }
      studios(isMain: true) { nodes { id name } }
      averageScore
      popularity
      favourites
      isAdult
    }
  }
}
"""


def _date_str(d: Optional[Dict]) -> Optional[str]:
    if not d:
        return None
    y, m, day = d.get("year"), d.get("month"), d.get("day")
    if y:
        parts = [str(y)]
        if m:
            parts.append(f"{m:02d}")
            if day:
                parts.append(f"{day:02d}")
        return "-".join(parts)
    return None


@register
class AniListAnimeSource(PaginatedJSONSource):
    name = "anilist_anime"
    id_field = "anilist_id"
    default_delay = 0.7

    base = GRAPHQL_URL
    accept = "application/json"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self.media_types: List[str] = ["ANIME"]

    @classmethod
    def add_cli_arguments(cls, parser) -> None:
        parser.add_argument("--type", choices=["ANIME", "MANGA", "ALL"], default="ANIME")

    def configure(self, args) -> None:
        mtype = getattr(args, "type", "ANIME")
        self.media_types = ["ANIME", "MANGA"] if mtype == "ALL" else [mtype]

    def initial_cursor(self) -> Dict[str, int]:
        return {"type_idx": 0, "page": 1}

    def map_row(self, m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        title = m.get("title") or {}
        studios = m.get("studios") or {}
        studio_nodes = studios.get("nodes") or []
        tags = m.get("tags") or []
        return {
            "anilist_id": m.get("id"),
            "mal_id": m.get("idMal"),
            "title_romaji": title.get("romaji"),
            "title_english": title.get("english"),
            "title_native": title.get("native"),
            "type": m.get("type"),
            "format": m.get("format"),
            "status": m.get("status"),
            "episodes": m.get("episodes"),
            "duration": m.get("duration"),
            "chapters": m.get("chapters"),
            "volumes": m.get("volumes"),
            "country_of_origin": m.get("countryOfOrigin"),
            "source_material": m.get("source"),
            "start_date": _date_str(m.get("startDate")),
            "end_date": _date_str(m.get("endDate")),
            "season": m.get("season"),
            "season_year": m.get("seasonYear"),
            "genres": m.get("genres") or [],
            "tags": [t.get("name") for t in tags if not t.get("isAdult") and t.get("name")],
            "studios": [s.get("name") for s in studio_nodes if s.get("name")],
            "studio_ids": [s.get("id") for s in studio_nodes if s.get("id")],
            "average_score": m.get("averageScore"),
            "popularity": m.get("popularity"),
            "favourites": m.get("favourites"),
            "is_adult": m.get("isAdult", False),
        }

    def _post(self, page: int, media_type: str) -> Optional[Dict[str, Any]]:
        """One GraphQL POST, reproducing the original's 429/400 handling.

        Retries in-place (like the original's outer ``while data is None:
        continue``) on rate-limit or transient HTTP error.
        """
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
            "Accept": self.accept,
        }
        payload = {
            "query": _QUERY,
            "variables": {"page": page, "perPage": PAGE_SIZE, "type": media_type},
        }
        while True:
            self.throttle.wait()
            try:
                resp = self.session().post(self.base, json=payload, headers=headers,
                                            timeout=self.timeout)
            except Exception:
                time.sleep(self.backoff_base)
                continue
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                time.sleep(retry_after)
                continue
            if resp.status_code == 400:
                # Past the last page — catalog for this type is complete.
                return {"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": []}}}
            try:
                resp.raise_for_status()
            except Exception:
                time.sleep(self.backoff_base)
                continue
            return resp.json()

    def fetch(self, cursor: Dict[str, int]):
        type_idx = int(cursor.get("type_idx", 0))
        page = int(cursor.get("page", 1))
        if type_idx >= len(self.media_types):
            return [], None
        media_type = self.media_types[type_idx]

        data = self._post(page, media_type)
        errors = (data or {}).get("errors")
        if errors:
            # Matches the original: a GraphQL error aborts this media type
            # (like its `break`) and moves on to the next one, if any.
            next_type_idx = type_idx + 1
            next_cursor = ({"type_idx": next_type_idx, "page": 1}
                           if next_type_idx < len(self.media_types) else None)
            return [], next_cursor

        page_data = (data.get("data") or {}).get("Page") or {}
        page_info = page_data.get("pageInfo") or {}
        media_list = page_data.get("media") or []

        rows = []
        for m in media_list:
            row = self.map_row(m)
            if row is not None:
                rows.append(row)

        if page_info.get("hasNextPage"):
            next_cursor = {"type_idx": type_idx, "page": page + 1}
        else:
            next_type_idx = type_idx + 1
            next_cursor = ({"type_idx": next_type_idx, "page": 1}
                           if next_type_idx < len(self.media_types) else None)
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(AniListAnimeSource))
