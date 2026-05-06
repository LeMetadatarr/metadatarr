"""Live test against VHS Legacy-style YouTube content.

Fetches real YouTube search results for classic VHS-era titles,
runs parse_title + classify_video_dict + signals_from_title, and
prints a structured report — no API keys required.

Run:  python examples/vhs_legacy_live_test.py
"""
from __future__ import annotations

import json
import sys
from typing import List, Dict, Any

from tutubo import search_yt, classify_video_dict, parse_title
from metadatarr import signals_from_title

# ---------------------------------------------------------------------------
# Fixtures — VHS-legacy-style titles captured from a live run.
# Run with --live to re-fetch from YouTube instead.
# ---------------------------------------------------------------------------

FIXTURES: List[Dict[str, Any]] = [
    # Documentary examples from FreeDocumentary channel
    {"title": "The Amazon: Earth's Greatest River | Full Documentary", "length": 5400, "description": ""},
    {"title": "WWII: The Battle of Berlin | Full Documentary", "length": 5100, "description": ""},
    {"title": "Secret History of the Freemasons | Free Documentary History", "length": 3600, "description": ""},
    {"title": "Living With Wolves | Wildlife Documentary | Full Length", "length": 2700, "description": ""},
    {"title": "20 Feet From Stardom (2013) | Full Documentary Movie", "length": 5700, "description": ""},
    # VHS Legacy
    {"title": "▶ Misty Brew's Creature Feature 'The Legacy' 1978 (Full Movie)", "length": 7079, "description": "Misty Brew's Creature Feature 'The Legacy' 1978 (Full Movie)"},
    {"title": "VHS Lives! A Shlockumentary (1080p) FULL MOVIE", "length": 8666, "description": "The VHS era rose quickly in the early 70's"},
    {"title": "Venice/Venice (1992) VHS Tape", "length": 6517, "description": "Shot half in Venice, Italy"},
    {"title": "Guitarman (1994), VHS full movie", "length": 5541, "description": "Filmed in Rouleau, Saskatchewan"},
    {"title": "Heartland Of Darkness | Full Movie | Classic 90s Horror", "length": 6091, "description": "In the small town of Copperton, Ohio"},
    {"title": "Casper Meets Wendy full movie", "length": 5400, "description": "I DO NOT OWN ANY RIGHTS ALL RIGHTS BELONG TO DISNEY!"},
    {"title": "The Secret of Roan Inish (1994) VHS Tape", "length": 5900, "description": ""},
    {"title": "Tiger Shark (1987) VHS Tape", "length": 5760, "description": ""},
    {"title": "The Cellar (1989) VHS Tape", "length": 5400, "description": ""},
    {"title": "Medicine River VHS Tape (1994)", "length": 5700, "description": ""},
    {"title": "Alien (1979) Director's Cut [Blu-ray]", "length": 6900, "description": ""},
    {"title": "Blade Runner: The Final Cut (1982/2007) [Theatrical vs Director's Cut]", "length": 7260, "description": ""},
    {"title": "The Wire - Season 2 Episode 1 (2002) [DVD]", "length": 3600, "description": ""},
    {"title": "Breaking Bad S03E07 One Minute (2010)", "length": 2700, "description": ""},
    {"title": "Dark Side of the Moon - Deluxe Edition (1973) [Vinyl] full album", "length": 2580, "description": "Pink Floyd concept album"},
    {"title": "greatest musical ever made #shorts #vhs #movies", "length": 16, "description": ""},
    {"title": "Invasion U.S.A. Vhs Street date ad . #music #vhs #movie", "length": 8, "description": ""},
]


def _live_fetch(query: str = "vhs legacy full movie classic", max_res: int = 20) -> List[Dict[str, Any]]:
    print(f"Fetching from YouTube: {query!r} …", flush=True)
    results = list(search_yt(query, max_res=max_res))
    return [
        {"title": r.get("title", ""), "length": r.get("length", 0),
         "description": r.get("description", "")}
        for r in results if r.get("title")
    ]


def _fmt_seconds(s: int) -> str:
    if not s:
        return "-"
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{sec:02d}s"


def run(items: List[Dict[str, Any]]) -> None:
    header = f"{'TITLE':<52} {'YEAR':>5}  {'CONTENT TYPE':<22} {'CUT/FMT':<16} {'MEDIUM':<9} {'LEN'}"
    print(header)
    print("-" * len(header))

    for item in items:
        title   = item.get("title", "")
        length  = int(item.get("length") or 0)
        desc    = item.get("description", "")

        ctype   = classify_video_dict({"title": title, "length": length, "description": desc})
        medium  = ctype.to_medium()
        parsed  = parse_title(title)
        sigs    = signals_from_title(title)

        year_s  = str(parsed.year) if parsed.year else "-"
        cut_s   = parsed.variant_kind.value if parsed.variant_kind else ""
        fmt_s   = parsed.source_format or ""
        cutfmt  = "/".join(filter(None, [cut_s, fmt_s])) or "-"

        title_trunc = title[:50].rstrip()

        print(f"{title_trunc:<52} {year_s:>5}  {ctype.value:<22} {cutfmt:<16} {medium:<9} {_fmt_seconds(length)}")


def main() -> None:
    live = "--live" in sys.argv
    items = _live_fetch() if live else FIXTURES
    run(items)


if __name__ == "__main__":
    main()
