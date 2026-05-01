#!/usr/bin/env python3
"""
channel_scanner.py — Scan a YouTube channel's uploads, deduplicate by signal_hash,
resolve each unique title via DVDCompare and other providers, and print a report.

Usage:
    python examples/channel_scanner.py                         # fixture mode
    python examples/channel_scanner.py --live [QUERY]          # live YouTube search
"""

import argparse
import sys
from typing import Dict, List, Optional

from tutubo import classify_video_dict, parse_title
from tutubo.content_type import ContentType

from metadatarr import signals_from_title
from metadatarr.resolve.base import resolve
from metadatarr.resolve.signals import Medium, signal_hash

FIXTURE_VIDEOS = [
    {"title": "Commando (1985) Full Movie VHS Legacy", "length": 6120},
    {"title": "Predator (1987) Full Movie | VHS Legacy Classic", "length": 6720},
    {"title": "Total Recall (1990) Full Movie VHS Legacy", "length": 7080},
    {"title": "RoboCop (1987) Classic Full Movie", "length": 6480},
    {"title": "Terminator (1984) Full Movie VHS Legacy", "length": 6660},
    {"title": "Conan the Barbarian (1982) Full Movie | Classic", "length": 7860},
    {"title": "First Blood (1982) Full Movie VHS Classic", "length": 5820},
    {"title": "Escape from New York (1981) Full Movie VHS Legacy", "length": 6000},
    {"title": "The Running Man (1987) Full Movie | VHS Legacy", "length": 5940},
    {"title": "Commando 1985 Full Movie (duplicate upload)", "length": 6120},
    {"title": "Predator 1987 Classic Full Movie", "length": 6720},
    {"title": "Mad Max Beyond Thunderdome (1985) Full Movie VHS", "length": 6360},
    {"title": "Invasion U.S.A. (1985) Full Movie VHS Legacy Classic", "length": 5700},
    {"title": "Missing in Action (1984) Full Movie | VHS Legacy", "length": 5580},
    {"title": "Navy SEALs (1990) Full Movie VHS Legacy Classic", "length": 5880},
]

MOVIE_CONTENT_TYPES = {ContentType.MOVIE, ContentType.DOCUMENTARY}
MIN_LENGTH = 2400


def fetch_live(query: str, max_results: int = 50) -> List[dict]:
    from tutubo import search_yt
    return list(search_yt(query, max_results=max_results))


def filter_videos(videos: List[dict]) -> List[dict]:
    kept = []
    for v in videos:
        ct = classify_video_dict(v)
        length = v.get("length") or v.get("duration") or 0
        if ct in MOVIE_CONTENT_TYPES and length > MIN_LENGTH:
            kept.append({**v, "_content_type": ct})
    return kept


def build_signals(video: dict):
    title_raw = video.get("title", "")
    parsed = parse_title(title_raw)
    sig = signals_from_title(title_raw)
    sig.medium = Medium.MOVIE
    if parsed.year:
        sig.year = parsed.year
    return sig


def collect_provider_names(result) -> List[str]:
    return sorted({m.provider for m in result.accepted})


def find_id(result, field: str) -> Optional[str]:
    val = getattr(result.external_ids, field, None)
    if val:
        return str(val)
    for m in result.accepted:
        v = getattr(m.external_ids, field, None)
        if v:
            return str(v)
    return None


def print_table(rows: List[dict]) -> None:
    headers = ["Title", "Year", "Content Type", "Providers", "IMDb", "DVDCompare"]
    col_widths = [max(len(h), max((len(str(r[h])) for r in rows), default=0)) for h in headers]

    def fmt_row(vals):
        return "  ".join(str(v).ljust(w) for v, w in zip(vals, col_widths))

    print(fmt_row(headers))
    print("  ".join("-" * w for w in col_widths))
    for row in rows:
        print(fmt_row([row[h] for h in headers]))


def run(videos: List[dict]) -> None:
    filtered = filter_videos(videos)
    print(f"Videos after filter: {len(filtered)} / {len(videos)}")
    print()

    seen_hashes: Dict[str, dict] = {}
    duplicates_skipped = 0

    for v in filtered:
        sig = build_signals(v)
        h = signal_hash(sig)
        if h in seen_hashes:
            duplicates_skipped += 1
        else:
            seen_hashes[h] = {"video": v, "signals": sig}

    table_rows = []
    for h, entry in seen_hashes.items():
        sig = entry["signals"]
        v = entry["video"]
        ct = v.get("_content_type", ContentType.MOVIE)

        result = resolve(sig)

        year = result.signals.year or sig.year or ""
        providers = collect_provider_names(result)
        imdb_id = find_id(result, "imdb") or ""
        dvd_id = find_id(result, "dvdcompare_id") or ""

        table_rows.append({
            "Title": result.signals.title or sig.title or v.get("title", ""),
            "Year": str(year),
            "Content Type": ct.value if hasattr(ct, "value") else str(ct),
            "Providers": ", ".join(providers) if providers else "none",
            "IMDb": imdb_id,
            "DVDCompare": dvd_id,
        })

    if table_rows:
        print_table(table_rows)
    else:
        print("No results.")

    print()
    print(f"Duplicates skipped: {duplicates_skipped}")


def main():
    parser = argparse.ArgumentParser(description="YouTube channel scanner with metadata resolution")
    parser.add_argument("--live", nargs="?", const="vhs legacy classic full movie",
                        metavar="QUERY", help="Live YouTube search query")
    parser.add_argument("--max-results", type=int, default=50,
                        help="Max results for live search (default: 50)")
    args = parser.parse_args()

    if args.live is not None:
        query = args.live
        print(f"[live] Searching YouTube: {query!r}")
        videos = fetch_live(query, max_results=args.max_results)
        print(f"[live] Fetched {len(videos)} results")
    else:
        print("[fixture] Using hardcoded titles (no YouTube API call)")
        videos = FIXTURE_VIDEOS

    print()
    run(videos)


if __name__ == "__main__":
    main()
