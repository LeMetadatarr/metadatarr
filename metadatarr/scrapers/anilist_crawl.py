"""AniList sequential ID scan — complete catalog in ~400 requests.

AniList's GraphQL endpoint caps paginated queries at page 50 (2500 results
max per media type). This scraper bypasses that entirely by using the
``id_in`` filter: query arbitrary batches of IDs directly, no pagination
needed. IDs are sequential integers starting at 1; the active range is
currently ~1-180,000.

Strategy:
  1. Walk the full ID range in ``BATCH_SIZE`` chunks using ``id_in``.
  2. Each request returns only the IDs that actually exist (possibly across
     several GraphQL pages if a chunk matches >50 titles); no wasted rows.
  3. Global dedup (by ``anilist_id``, via the engine) skips ids already
     harvested — including by :mod:`metadatarr.scrapers.anilist_anime`,
     *if* run against the same output directory, since both scrapers key
     rows the same way.

Like the original, this ID scan tops up the shared ``anilist_anime`` dataset:
``dataset_name = "anilist_anime"`` routes rows into that JSONL while the
checkpoint stays under this scraper's own ``anilist_crawl`` name. Dedup reads
the shared file, so it never re-adds anime the paginated crawler already got.

Run it::

    python -m metadatarr.scrapers anilist_crawl [--output DIR] [--delay SECS]
                                                 [--max-id N]
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

GRAPHQL_URL = "https://graphql.anilist.co"
BATCH_SIZE = 500  # ids per request (well above perPage=50 — AniList returns whichever exist)
DEFAULT_MAX_ID = 200_000

_BATCH_QUERY = """
query($ids: [Int], $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(id_in: $ids, sort: ID) {
      id idMal
      title { romaji english native }
      type format status
      episodes duration chapters volumes
      countryOfOrigin source
      startDate { year month day }
      endDate { year month day }
      season seasonYear
      genres
      tags { name isAdult }
      studios(isMain: true) { nodes { id name } }
      averageScore popularity favourites isAdult
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
class AniListCrawlSource(PaginatedJSONSource):
    name = "anilist_crawl"
    # Tops up the shared anilist_anime dataset (identical row schema) while
    # keeping its own checkpoint — matches the original, which appended into
    # anilist_anime.jsonl. Dedup reads that shared file, so it won't re-add
    # anime the primary scraper already captured.
    dataset_name = "anilist_anime"
    id_field = "anilist_id"
    default_delay = 0.7

    base = GRAPHQL_URL
    accept = "application/json"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self.max_id = DEFAULT_MAX_ID

    @classmethod
    def add_cli_arguments(cls, parser) -> None:
        parser.add_argument("--max-id", type=int, default=DEFAULT_MAX_ID,
                            help="Upper bound of ID range to scan (default 200,000)")

    def configure(self, args) -> None:
        self.max_id = getattr(args, "max_id", DEFAULT_MAX_ID)

    def initial_cursor(self) -> int:
        return 1

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

    def _fetch_page(self, ids: List[int], page: int) -> "tuple[List[Dict[str, Any]], bool]":
        """Return (media_list, has_next_page). Retries on 429; gives up (empty,
        False) on other non-200s or transport errors, matching the original."""
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
            "Accept": self.accept,
        }
        payload = {"query": _BATCH_QUERY, "variables": {"ids": ids, "page": page}}
        self.throttle.wait()
        try:
            resp = self.session().post(self.base, json=payload, headers=headers,
                                        timeout=self.timeout)
        except Exception:
            return [], False
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            time.sleep(retry_after)
            return self._fetch_page(ids, page)
        if resp.status_code != 200:
            return [], False
        data = resp.json()
        if data.get("errors"):
            return [], False
        page_data = (data.get("data") or {}).get("Page") or {}
        has_next = (page_data.get("pageInfo") or {}).get("hasNextPage", False)
        return page_data.get("media") or [], has_next

    def _fetch_batch(self, ids: List[int]) -> List[Dict[str, Any]]:
        """Fetch all matching media for the given id_in list, paginating if needed."""
        all_media: List[Dict[str, Any]] = []
        page = 1
        while True:
            media, has_next = self._fetch_page(ids, page)
            all_media.extend(media)
            if not has_next:
                break
            page += 1
        return all_media

    def fetch(self, cursor: int):
        chunk_start = int(cursor or 1)
        if chunk_start > self.max_id:
            return [], None

        chunk_end = min(chunk_start + BATCH_SIZE - 1, self.max_id)
        ids = list(range(chunk_start, chunk_end + 1))

        media_list = self._fetch_batch(ids)

        rows = []
        for m in media_list:
            row = self.map_row(m)
            if row is not None:
                rows.append(row)

        next_cursor = chunk_end + 1 if chunk_end < self.max_id else None
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(AniListCrawlSource))
