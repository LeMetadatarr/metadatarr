"""Steam game catalog crawler.

Uses SteamSpy (steamspy.com/api.php?request=all&page=N) to get the full
catalog in pages of 1000 entries. SteamSpy already includes developer,
publisher, owner estimates, and review counts - no per-app detail calls
needed.

SteamSpy's page payload is a ``{appid: entry}`` object, not a list under a
results key, so :meth:`fetch` is overridden directly (cursor is the page
number, end-of-catalog is an empty page). The original's optional
``--enrich`` flag (per-app Steam store detail calls) isn't exposed by the
engine's standard CLI flags and is dropped here; the default (and only)
behaviour ported is the non-enriched SteamSpy-only crawl.

Run it::

    python -m metadatarr.scrapers steam_games [--output DIR] [--limit N] [--delay SECS]
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

STEAMSPY_URL = "https://steamspy.com/api.php"


@register
class SteamGamesSource(PaginatedJSONSource):
    name = "steam_games"
    id_field = "steam_appid"
    default_delay = 1.5

    base = STEAMSPY_URL

    def initial_cursor(self) -> int:
        return 0

    def map_row(self, appid: str, d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        price_raw = d.get("price") or "0"
        try:
            price_usd = int(price_raw) / 100
        except (ValueError, TypeError):
            price_usd = None
        return {
            "steam_appid": d.get("appid") or int(appid),
            "name": d.get("name"),
            "developer": d.get("developer"),
            "publisher": d.get("publisher"),
            "score_rank": d.get("score_rank") or None,
            "positive_reviews": d.get("positive"),
            "negative_reviews": d.get("negative"),
            "owners": d.get("owners"),
            "average_playtime_forever": d.get("average_forever"),
            "average_playtime_2weeks": d.get("average_2weeks"),
            "median_playtime_forever": d.get("median_forever"),
            "price_usd": price_usd,
            "discount_pct": d.get("discount") or None,
            "ccu": d.get("ccu"),
            # enriched fields (left unset - --enrich isn't ported)
            "type": None,
            "genres": [],
            "categories": [],
            "release_date": None,
            "is_free": None,
            "platforms_windows": None,
            "platforms_mac": None,
            "platforms_linux": None,
            "metacritic_score": None,
            "short_description": None,
        }

    def fetch(self, cursor: int):
        page = int(cursor)
        data = self.get_json(self.base, {"request": "all", "page": page})

        if not data:
            return [], None

        rows = []
        for appid, entry in data.items():
            row = self.map_row(appid, entry)
            if row is not None:
                rows.append(row)
        return rows, page + 1


if __name__ == "__main__":
    raise SystemExit(run_cli(SteamGamesSource))
