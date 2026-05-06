"""Discover all fanedits available for a director's filmography.

User story: "I'm a Ridley Scott fan working through his back-catalogue. For
each film I want to know: does a director's cut exist, and how many fanedits
has the community made? I want a ranked summary so I know which titles have
the most community activity before I decide what to watch."

Flow:
  1. Define a filmography list (title + year + IMDb id)
  2. For each film, resolve() with include_variants=True
  3. Separate official cuts (directors, extended) from fanedits (fanedit_id set)
  4. Print per-film summary + rank by fanedit count

Requires:
    pip install metadatarr[fanedit]
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

import metadatarr.resolve.providers  # noqa: F401 — trigger provider self-registration
from metadatarr.resolve import resolve
from metadatarr.resolve.entities import Role
from mediavocab import MediaType
from mediavocab.models.signals import Signals

# ---------------------------------------------------------------------------
# Filmography — Ridley Scott films with well-known alternate cuts
# ---------------------------------------------------------------------------

FILMOGRAPHY = [
    {"title": "Alien",             "year": 1979, "imdb": "tt0078748"},
    {"title": "Blade Runner",      "year": 1982, "imdb": "tt0083658"},
    {"title": "Legend",            "year": 1985, "imdb": "tt0089469"},
    {"title": "Black Hawk Down",   "year": 2001, "imdb": "tt0265086"},
    {"title": "Kingdom of Heaven", "year": 2005, "imdb": "tt0320661"},
]

@dataclass
class FilmSummary:
    title: str
    year: int
    imdb: Optional[str]
    fanedit_count: int = 0
    top_fanedits: List[str] = field(default_factory=list)


def discover(film: dict) -> FilmSummary:
    result = resolve(Signals(
        title=film["title"],
        year=film["year"],
        medium=MediaType.MOVIE,
        include_variants=True,
    ), max_workers=4)

    releases = result.relations.get(Role.RELEASE, [])
    # Everything in relations[RELEASE] comes from pyfanedit — all are fanedits.
    # fanedit_id from search() is None; the url lives in extra["fanedit_url"].
    return FilmSummary(
        title=film["title"],
        year=film["year"],
        imdb=result.external_ids.imdb or film["imdb"],
        fanedit_count=len(releases),
        top_fanedits=[r.name for r in releases[:3]],
    )


def main() -> None:
    print("Scanning Ridley Scott filmography for fanedits…\n")

    summaries: List[FilmSummary] = []
    for film in FILMOGRAPHY:
        print(f"  resolving {film['title']} ({film['year']})…", end=" ", flush=True)
        try:
            s = discover(film)
            summaries.append(s)
            print(f"{s.fanedit_count} fanedit(s)")
        except Exception as exc:
            print(f"failed: {exc}")
        time.sleep(1)

    # Rank by fanedit activity
    summaries.sort(key=lambda s: s.fanedit_count, reverse=True)

    print("\n" + "=" * 62)
    print("  Fanedit activity — Ridley Scott filmography")
    print("=" * 62)
    print(f"  {'Title':<26}  {'Year'}  Fanedits on IFDB")
    print(f"  {'-'*26}  {'-'*4}  ----------------")
    for s in summaries:
        print(f"  {s.title:<26}  {s.year}  {s.fanedit_count}")

    print()
    for s in summaries:
        if not s.fanedit_count:
            continue
        print(f"  {s.title} ({s.year})")
        for fe in s.top_fanedits:
            print(f"    {fe}")
        if s.fanedit_count > 3:
            print(f"    … and {s.fanedit_count - 3} more")
        print()


if __name__ == "__main__":
    main()
