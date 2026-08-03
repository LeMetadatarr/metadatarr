"""Steam game catalog crawler.

Uses SteamSpy (steamspy.com/api.php?request=all&page=N) to get the full
catalog in pages of 1000 entries. SteamSpy already includes developer,
publisher, owner estimates, and review counts - no per-app detail calls
needed.

SteamSpy's page payload is a ``{appid: entry}`` object, not a list under a
results key, so :meth:`fetch` is overridden directly (cursor is the page
number, end-of-catalog is an empty page). ``--enrich`` optionally calls the
Steam store detail API per app for genres/platforms/metacritic (registered via
:meth:`add_cli_arguments`).

Run it::

    python -m metadatarr.scrapers steam_games [--output DIR] [--limit N] [--delay SECS] [--enrich]
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, Throttle, register, run_cli

STEAMSPY_URL = "https://steamspy.com/api.php"
DETAIL_URL = "https://store.steampowered.com/api/appdetails"


@register
class SteamGamesSource(PaginatedJSONSource):
    name = "steam_games"
    id_field = "steam_appid"
    default_delay = 1.5

    base = STEAMSPY_URL

    def __init__(self, **kw):
        super().__init__(**kw)
        self.enrich = False
        self._detail_throttle = Throttle(min_delay=1.0)

    @classmethod
    def add_cli_arguments(cls, parser):
        parser.add_argument("--enrich", action="store_true",
                            help="Also call the Steam store API for genres/platforms")

    def configure(self, args):
        self.enrich = getattr(args, "enrich", False)

    def initial_cursor(self) -> int:
        return 0

    def _fetch_detail(self, appid: int) -> Optional[Dict[str, Any]]:
        self._detail_throttle.wait()
        try:
            resp = self.session().get(
                DETAIL_URL,
                params={"appids": appid, "cc": "us", "l": "en"},
                timeout=20,
            )
            if resp.status_code == 429:
                time.sleep(60)
                return None
            if resp.status_code != 200:
                return None
            entry = resp.json().get(str(appid)) or {}
            if not entry.get("success"):
                return None
            return entry.get("data")
        except Exception:
            return None

    def _apply_detail(self, row: Dict[str, Any], d: Dict[str, Any]) -> None:
        price = d.get("price_overview") or {}
        meta = d.get("metacritic") or {}
        platforms = d.get("platforms") or {}
        release = d.get("release_date") or {}
        row["type"] = d.get("type")
        row["genres"] = [g.get("description") for g in (d.get("genres") or []) if g.get("description")]
        row["categories"] = [c.get("description") for c in (d.get("categories") or []) if c.get("description")]
        row["release_date"] = release.get("date")
        row["is_free"] = d.get("is_free", False)
        row["price_usd"] = price.get("final") and price["final"] / 100
        row["platforms_windows"] = platforms.get("windows")
        row["platforms_mac"] = platforms.get("mac")
        row["platforms_linux"] = platforms.get("linux")
        row["metacritic_score"] = meta.get("score")
        row["short_description"] = d.get("short_description")

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
            if row is None:
                continue
            if self.enrich:
                detail = self._fetch_detail(row["steam_appid"])
                if detail:
                    self._apply_detail(row, detail)
            rows.append(row)
        return rows, page + 1


if __name__ == "__main__":
    raise SystemExit(run_cli(SteamGamesSource))
