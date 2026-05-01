"""Walk a YouTube channel and resolve each video title to canonical film metadata.

User story: Mosfilm's English channel (https://www.youtube.com/@Mosfilm_eng)
publishes full Soviet-era films.  Given only the channel URL I want, for each
upload:

  1. Parse the channel with tutubo → title, year, video_id, watch_url
  2. Clean the title (strip "| DRAMA | with english subtitles" noise)
  3. Fan out to every active movie provider via search() → ranked candidates
  4. Score and rank candidates by title similarity × provider confidence
  5. Pick the best candidate and consolidate → IMDb, TMDB, Wikidata
  6. Combine: watch_url (playable stream) + canonical metadata IDs

The ranking step (3-4) is explicit so you can see which providers agreed,
which were dropped, and how confident the final answer is.

Requirements::

    pip install metadatarr   # tutubo is a required dependency

Run it::

    python examples/channel_to_metadata.py
    python examples/channel_to_metadata.py https://www.youtube.com/@Mosfilm_eng 10
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from tutubo import Channel, classify_video_dict

from metadatarr.resolve import Medium, Signals, consolidate, search
from metadatarr.resolve.base import ProviderMatch

CHANNEL_URL = "https://www.youtube.com/@Mosfilm_eng"
MAX_VIDEOS   = 8   # keep the demo fast; bump or remove to scan the full channel

# Minimum combined score to consider a candidate a confident match.
# score = provider_confidence × title_similarity
SCORE_THRESHOLD = 0.35


# ---------------------------------------------------------------------------
# Title cleaning
# ---------------------------------------------------------------------------

def _clean_title(raw: str) -> tuple[str, Optional[int]]:
    """Extract (clean_title, year) from Mosfilm-style video title strings.

    Input examples:
      "Solaris (1972) | Sci-Fi MASTERPIECE | Full Movie with English Subtitles"
      "The Cranes Are Flying (1957) | DRAMA"
      "Lenin in Paris: A Revolutionary's Story"
    """
    m_year = re.search(r"\((\d{4})\)", raw)
    year   = int(m_year.group(1)) if m_year else None
    title  = re.sub(r"\s*\(\d{4}\)\s*", " ", raw)   # remove (YYYY)
    title  = re.split(r"\s*\|", title)[0].strip()     # drop pipe-suffixes
    title  = re.sub(r"\s+", " ", title).strip()
    return title, year


# ---------------------------------------------------------------------------
# Candidate ranking
# ---------------------------------------------------------------------------

def _title_sim(query: str, candidate: str) -> float:
    return SequenceMatcher(None, query.lower().strip(),
                           candidate.lower().strip()).ratio()


def _score(query_title: str, match: ProviderMatch,
           query_year: Optional[int] = None) -> float:
    """Combined score = provider confidence × title similarity × year factor.

    Year factor: 1.0 if query has no year or candidate has no year (unknown),
    1.0 if years match exactly, 0.0 if years are known and differ.
    This hard-discards wrong-year matches (e.g. Sisters 2015 vs query year 1957).
    """
    sim = _title_sim(query_title, match.signals.title or "")
    candidate_year = match.signals.year
    if query_year and candidate_year and query_year != candidate_year:
        year_factor = 0.0
    else:
        year_factor = 1.0
    return match.confidence * sim * year_factor


def _rank_candidates(query_title: str,
                     candidates: list[ProviderMatch],
                     query_year: Optional[int] = None) -> list[tuple[float, ProviderMatch]]:
    """Return (score, match) pairs sorted by score descending."""
    scored = [(round(_score(query_title, c, query_year), 4), c) for c in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Result record
# ---------------------------------------------------------------------------

@dataclass
class ChannelFilmRecord:
    raw_title:   str
    clean_title: str
    year:        Optional[int]
    video_id:    str
    watch_url:   str
    imdb:        Optional[str]   = None
    tmdb:        Optional[int]   = None
    wikidata:    Optional[str]   = None
    best_score:  float           = 0.0
    providers:   list[str]       = field(default_factory=list)
    matched:     bool            = False   # score cleared threshold
    no_ids:      bool            = False   # matched but providers returned no external IDs


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def _fetch_videos(channel_url: str, max_videos: int) -> list:
    ch = Channel(channel_url)
    print(f"  channel : {ch.channel_name}  ({ch.subscribers})")
    print(f"  id      : {ch.channel_id}")
    print(f"  desc    : {(ch.description or '').splitlines()[0][:80]}")
    print()
    videos = []
    for v in ch.videos:
        videos.append(v)
        if len(videos) >= max_videos:
            break
    return videos


def _infer_medium(video) -> Medium:
    """Use tutubo's classifier to derive a metadatarr Medium from a Video object."""
    ctype = classify_video_dict({
        "title":       video.title or "",
        "description": getattr(video, "description", "") or "",
        "length":      getattr(video, "length", 0) or 0,
        "is_live":     getattr(video, "is_live", False),
    })
    medium_str = ctype.to_medium()
    try:
        return Medium(medium_str)
    except ValueError:
        return Medium.OTHER


def _resolve_title(clean_title: str,
                   year: Optional[int],
                   medium: Medium = Medium.OTHER) -> tuple[list, list[tuple[float, ProviderMatch]]]:
    """Search all active providers and return (raw_candidates, ranked_scored)."""
    sig        = Signals(title=clean_title, year=year, medium=medium)
    candidates = search(sig)
    ranked     = _rank_candidates(clean_title, candidates, query_year=year)
    return candidates, ranked


def _process(channel_url: str, max_videos: int) -> list[ChannelFilmRecord]:
    videos = _fetch_videos(channel_url, max_videos)
    records: list[ChannelFilmRecord] = []

    for v in videos:
        raw           = v.title
        clean, year   = _clean_title(raw)
        medium        = _infer_medium(v)

        print(f"  [{v.video_id}]  {raw[:72]}")
        print(f"    query: {clean!r}" + (f"  ({year})" if year else "") + f"  [{medium.value}]")

        candidates, ranked = _resolve_title(clean, year, medium=medium)

        # Print top-3 ranked candidates so the ranking is visible
        for rank, (score, m) in enumerate(ranked[:3], start=1):
            sim   = _title_sim(clean, m.signals.title or "")
            cyear = f" [{m.signals.year}]" if m.signals.year else ""
            print(f"    {rank}. {m.provider:<14} conf={m.confidence:.2f} "
                  f"× sim={sim:.2f} = score={score:.2f}  "
                  f"{m.signals.title!r}{cyear}  "
                  f"imdb={m.external_ids.imdb}  tmdb={m.external_ids.tmdb_movie}")

        # Accept candidates that clear the score threshold, then consolidate
        accepted_candidates = [m for score, m in ranked if score >= SCORE_THRESHOLD]

        if accepted_candidates:
            sig    = Signals(title=clean, year=year, medium=Medium.MOVIE)
            result = consolidate(accepted_candidates, local=sig)
            ids    = result.external_ids
            best_score = ranked[0][0] if ranked else 0.0

            has_ids = bool(ids.imdb or ids.tmdb_movie or ids.wikidata)
            rec = ChannelFilmRecord(
                raw_title   = raw,
                clean_title = clean,
                year        = year,
                video_id    = v.video_id,
                watch_url   = v.watch_url,
                imdb        = ids.imdb,
                tmdb        = ids.tmdb_movie,
                wikidata    = ids.wikidata,
                best_score  = best_score,
                providers   = [m.provider for m in result.accepted],
                matched     = True,
                no_ids      = not has_ids,
            )
            status = []
            if ids.imdb:       status.append(f"imdb={ids.imdb}")
            if ids.tmdb_movie: status.append(f"tmdb={ids.tmdb_movie}")
            if ids.wikidata:   status.append(f"wikidata={ids.wikidata}")
            verdict = f"✓ score={best_score:.2f}  {', '.join(status) or '(matched, no ids)'}"
        else:
            rec = ChannelFilmRecord(
                raw_title   = raw,
                clean_title = clean,
                year        = year,
                video_id    = v.video_id,
                watch_url   = v.watch_url,
                best_score  = ranked[0][0] if ranked else 0.0,
            )
            verdict = f"✗ best_score={rec.best_score:.2f} < threshold={SCORE_THRESHOLD}"

        print(f"    → {verdict}")
        records.append(rec)
        print()

    return records


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _print_summary(records: list[ChannelFilmRecord]) -> None:
    with_ids   = [r for r in records if r.matched and not r.no_ids]
    matched    = [r for r in records if r.matched]
    low_conf   = [r for r in records if not r.matched]

    print("=" * 74)
    print(f"  RESULTS: {len(with_ids)}/{len(records)} with external IDs  "
          f"| {len(matched)} matched  (threshold={SCORE_THRESHOLD})")
    print("=" * 74)
    print()
    print(f"  {'Title':<32}  {'Year':>4}  {'Score':>5}  {'IMDb':<12}  {'TMDB':>6}")
    print(f"  {'-'*32}  {'-'*4}  {'-'*5}  {'-'*12}  {'-'*6}")
    for r in records:
        yr    = str(r.year) if r.year else "    "
        imdb  = r.imdb or "-"
        tmdb  = str(r.tmdb) if r.tmdb else "-"
        if r.matched and not r.no_ids:
            mark = "✓"
        elif r.matched:
            mark = "~"   # matched but no external IDs
        else:
            mark = " "
        score = f"{r.best_score:.2f}"
        print(f"  {mark} {r.clean_title[:31]:<31}  {yr:>4}  {score:>5}  {imdb:<12}  {tmdb:>6}")
        print(f"    ▶ {r.watch_url}")

    if low_conf:
        print(f"\n  Low-confidence ({len(low_conf)}) — "
              f"best score was below threshold {SCORE_THRESHOLD}:")
        for r in low_conf:
            s = f" (score={r.best_score:.2f})" if r.best_score else ""
            print(f"    • {r.clean_title}" + (f" ({r.year})" if r.year else "") + s)
        print()
        print("  Options:")
        print("  - Lower SCORE_THRESHOLD if you trust these providers")
        print("  - Add a METADATARR_TMDB_KEY env var to activate the TMDB provider")
        print("  - Or declare known video_ids in mappings.toml:")
        for r in low_conf[:2]:
            print(f"\n    [[movie]]")
            print(f"    name             = {r.clean_title!r}")
            print(f"    # imdb           = \"tt0000000\"")
            print(f"    youtube_video_id = {r.video_id!r}")


def main() -> None:
    args        = sys.argv[1:]
    channel_url = args[0] if args else CHANNEL_URL
    max_videos  = int(args[1]) if len(args) > 1 else MAX_VIDEOS

    print("=" * 74)
    print("  YouTube channel → film metadata  (search + rank)")
    print(f"  {channel_url}")
    print(f"  score = provider_confidence × title_similarity  "
          f"(threshold={SCORE_THRESHOLD})")
    print("=" * 74)
    print()

    records = _process(channel_url, max_videos)
    _print_summary(records)


if __name__ == "__main__":
    main()
