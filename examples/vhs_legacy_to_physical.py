"""Map VHS Legacy YouTube uploads to physical VHS / disc releases via DVDCompare.

Pipeline:
  1. Fetch search results for VHS Legacy-style titles (fixtures or --live).
  2. Parse each title (year, cut, format) and classify content type.
  3. Keep only movie-class results with a recognisable year.
  4. For each movie, query DVDCompare for physical release records.
  5. Print a table: YouTube title → clean title / year → physical releases found.

Run:
  python examples/vhs_legacy_to_physical.py           # fixture data
  python examples/vhs_legacy_to_physical.py --live    # live YouTube fetch
"""
from __future__ import annotations

import sys
import time
from typing import List, Dict, Any, Optional

from tutubo import search_yt, classify_video_dict, parse_title
from tutubo.content_type import ContentType
from metadatarr.client import DVDCompareClient
from metadatarr.resolve.signals import Signals, Medium

# ---------------------------------------------------------------------------
# Fixtures — captured from a live VHS-legacy search run
# ---------------------------------------------------------------------------

FIXTURES: List[Dict[str, Any]] = [
    {"title": "The Secret of Roan Inish (1994) VHS Tape",        "length": 5940},
    {"title": "Guitarman (1994), VHS full movie",                  "length": 5541},
    {"title": "Tiger Shark (1987) VHS Tape",                       "length": 5760},
    {"title": "The Cellar (1989) VHS Tape",                        "length": 5400},
    {"title": "Medicine River VHS Tape (1994)",                    "length": 5700},
    {"title": "Venice/Venice (1992) VHS Tape",                     "length": 6517},
    {"title": "Martin Sheen & Albert Finney: LOOPHOLE (1981) | Bank Heist Thriller", "length": 6180},
    {"title": "Heartland Of Darkness | Full Movie | Classic 90s Horror", "length": 6091},
    {"title": "Casper Meets Wendy full movie",                     "length": 5400},
    {"title": "Coonskin | Full Blaxploitation Movie | Barry White", "length": 4800},
    {"title": "Forever Mine | FULL MOVIE | Thriller, Romance",     "length": 6840},
    {"title": "20,000 Leagues Under The Sea | FULL MOVIE | 1997",  "length": 5400},
    # Shorts / ads — should be filtered out
    {"title": "Lost Boys VHS true first print info . #movie #vhs", "length": 27},
    {"title": "Invasion U.S.A. Vhs Street date ad . #vhs #movie",  "length": 8},
]

_MOVIE_CONTENT_TYPES = {
    ContentType.MOVIE, ContentType.DOCUMENTARY,
    ContentType.ANIME, ContentType.VIDEO,
}


def _live_fetch(query: str = "vhs legacy full movie classic", max_res: int = 25) -> List[Dict[str, Any]]:
    print(f"Fetching YouTube: {query!r} …", flush=True)
    results = list(search_yt(query, max_res=max_res))
    return [
        {"title": r.get("title", ""), "length": r.get("length", 0)}
        for r in results if r.get("title")
    ]


def _is_movie_candidate(item: Dict[str, Any]) -> bool:
    """True when the item looks like a feature film (not a short/ad/clip)."""
    length = int(item.get("length") or 0)
    if length < 2400:   # under 40 minutes → skip
        return False
    ctype = classify_video_dict({"title": item["title"], "length": length})
    return ctype in _MOVIE_CONTENT_TYPES


def _lookup_physical(client: DVDCompareClient, title: str, year: Optional[int]) -> list:
    """Search DVDCompare for physical releases of a film."""
    try:
        hits = client.search(title)
    except Exception as exc:
        return [f"(search error: {exc})"]
    if not hits:
        return []

    # Filter to hits within 2 years of the expected year when we have one
    if year:
        hits = [h for h in hits if not _year_from(h.title) or abs((_year_from(h.title) or year) - year) <= 2] or hits

    out = []
    for h in hits[:3]:
        parts = [h.title]
        if h.version:
            parts.append(h.version)
        if h.region:
            parts.append(f"[{h.region}]")
        if h.disc_format:
            parts.append(h.disc_format)
        out.append(" | ".join(parts))
    return out


def _year_from(title: str) -> Optional[int]:
    return parse_title(title).year


def run(items: List[Dict[str, Any]]) -> None:
    client = DVDCompareClient()

    print(f"\n{'YOUTUBE TITLE':<52} {'YEAR':>5}  PHYSICAL RELEASES (DVDCompare)")
    print("-" * 110)

    for item in items:
        raw_title = item.get("title", "")
        if not _is_movie_candidate(item):
            continue

        parsed = parse_title(raw_title)
        clean  = parsed.title
        year   = parsed.year

        releases = _lookup_physical(client, clean, year)

        title_trunc = raw_title[:50].rstrip()
        year_s = str(year) if year else "-"

        if not releases:
            print(f"{title_trunc:<52} {year_s:>5}  (no physical record found)")
        else:
            print(f"{title_trunc:<52} {year_s:>5}  {releases[0]}")
            for r in releases[1:]:
                print(f"{'':>59}  {r}")

        time.sleep(0.3)   # be polite to dvdcompare.net


def main() -> None:
    live = "--live" in sys.argv
    items = _live_fetch() if live else FIXTURES
    run(items)


if __name__ == "__main__":
    main()
