"""Rank and filter fanedits to help a user pick one to watch tonight.

User story: "I want to watch a fan-edited version of The Phantom Menace but
there are dozens on IFDB and I don't know where to start. Show me the
highest-rated ones, filter to edits that actually remove things (not just
add colour-grading), and give me the cuts summary for the top 3 so I can
decide."

Flow:
  1. resolve() with include_variants=True to collect all IFDB ids
  2. Fetch FaneditDetail for each (batch, with rate-limiting)
  3. Filter to fanedit_type == "FanFix" (removes content) or any type the
     user specifies
  4. Sort by user_rating descending, print top N with cuts preview

Requires:
    pip install metadatarr   # pyfanedit is a core dependency, no extra needed
"""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

import metadatarr.resolve.providers  # noqa: F401
from metadatarr.resolve import resolve
from mediavocab import MediaType
from mediavocab.models.signals import Signals

FILM_TITLE = "Blade Runner"
FILM_YEAR = 1982

# Filter: None = show all types. String match is case-insensitive substring.
# Common types on IFDB: "FanFix", "FanMix", "Preservation", "Color Grading",
# "Audio/Visual Edit", "Shorts", "Special Edition"
FILTER_TYPE: Optional[str] = None   # show all types for this demo

TOP_N = 5           # how many to show detail for
FETCH_LIMIT = 30    # max detail fetches (each is one HTTP request)
SLEEP_S = 1.5       # be polite to fanedit.org


def _rating_key(detail) -> float:
    """Sort key: prefer user_rating; fall back to editor_rating."""
    if detail.user_rating is not None and detail.user_rating_count:
        return detail.user_rating
    if detail.editor_rating is not None:
        return detail.editor_rating / 10.0  # editor_rating is 0-100
    return 0.0


def _type_matches(detail, filter_type: Optional[str]) -> bool:
    if filter_type is None:
        return True
    return filter_type.lower() in (detail.fanedit_type or "").lower()


def main() -> None:
    from pyfanedit import FaneditClient
    client = FaneditClient()

    # --- Step 1: collect all fanedit ids ---------------------------------
    print(f"Resolving {FILM_TITLE!r}…")
    result = resolve(Signals(
        title=FILM_TITLE,
        year=FILM_YEAR,
        medium=MediaType.MOVIE,
        include_variants=True,
    ), max_workers=4)

    releases = result.variants
    print(f"  {len(releases)} fanedit(s) found on IFDB")

    if not releases:
        print("  No fanedits found — check network connectivity")
        return

    # --- Step 2: fetch detail for up to FETCH_LIMIT entries --------------
    # Search results carry the fanedit url in extra["fanedit_url"]; fanedit_id
    # is only populated after a get_detail() call.
    print(f"\nFetching detail for up to {FETCH_LIMIT} fanedits…")
    details = []
    for i, variant in enumerate(releases[:FETCH_LIMIT]):
        url = (variant.external_ids.extra or {}).get("fanedit_url")
        if not url:
            continue
        try:
            detail = client.get_detail(url)
            details.append(detail)
        except Exception as exc:
            print(f"  [{i+1}/{min(len(releases), FETCH_LIMIT)}] {url} failed: {exc}")
        time.sleep(SLEEP_S)

    print(f"  fetched {len(details)} detail pages")

    # --- Step 3: filter by type ------------------------------------------
    if FILTER_TYPE:
        filtered = [d for d in details if _type_matches(d, FILTER_TYPE)]
        print(f"  {len(filtered)} match type filter {FILTER_TYPE!r}")
    else:
        filtered = details

    if not filtered:
        print("  No results after filtering — try relaxing FILTER_TYPE")
        return

    # --- Step 4: rank and display ----------------------------------------
    ranked = sorted(filtered, key=_rating_key, reverse=True)

    print(f"\n{'='*62}")
    print(f"  Top {min(TOP_N, len(ranked))} {FILTER_TYPE or 'all-type'} fanedits of {FILM_TITLE!r}")
    print(f"{'='*62}")

    for i, d in enumerate(ranked[:TOP_N], 1):
        user_r = f"{d.user_rating:.1f}/5 ({d.user_rating_count} votes)" \
            if d.user_rating and d.user_rating_count else "no user rating"
        editor_r = f"{d.editor_rating}/100" if d.editor_rating else "no editor rating"
        runtime = str(d.fanedit_running_time) if d.fanedit_running_time else "runtime unknown"
        time_cut = f"-{d.time_cut}" if d.time_cut else ""
        time_added = f"+{d.time_added}" if d.time_added else ""
        delta = f"  [{time_cut}{time_added}]" if (time_cut or time_added) else ""

        print(f"\n  #{i}  {d.title}")
        print(f"       faneditor   : {d.faneditor or 'unknown'}")
        print(f"       type        : {d.fanedit_type or 'unknown'}")
        print(f"       runtime     : {runtime}{delta}")
        print(f"       user rating : {user_r}")
        print(f"       editor score: {editor_r}")
        print(f"       url         : {d.url}")

        if d.intention:
            intent = d.intention[:160].replace("\n", " ")
            print(f"       intention   : {intent}…" if len(d.intention) > 160 else f"       intention   : {intent}")

        if d.cuts_and_additions:
            preview = d.cuts_and_additions[:240].replace("\n", " ")
            print(f"       cuts        : {preview}…" if len(d.cuts_and_additions) > 240 else f"       cuts        : {preview}")

    if len(ranked) > TOP_N:
        print(f"\n  … and {len(ranked) - TOP_N} more after filtering")

    print()


if __name__ == "__main__":
    main()
