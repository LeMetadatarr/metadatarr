"""Compare physical releases and fanedits across the Alien trilogy.

Films covered:
    Alien (1979)        — theatrical + Director's Cut (2003 restoration)
    Aliens (1986)       — theatrical + Special Edition (17 min longer)
    Alien 3 (1992)      — theatrical + Assembly Cut (restored workprint)

What this script does:
    1. Uses dvdcompare.net to list every known regional disc release for each
       film, surfacing cut/version metadata for Theatrical vs Director's Cut.
    2. Uses the Signals system to model each cut as a distinct canonical
       record and show how compare() catches cut conflicts.
    3. Runs resolve() with include_variants=True to collect fanedits from
       fanedit.org (IFDB) for each title.
    4. Prints a cross-film summary table.

Note: Discogs is NOT used here.  Discogs is a music database — it has
excellent coverage of music video LaserDiscs and soundtrack vinyl, but
sparse-to-zero coverage of narrative feature films on any video format.
For LaserDisc / VHS research on feature films, use dvdcompare.net.
See examples/discogs_music_video.py for Discogs usage.

Known dvdcompare.net film IDs (as of 2026):
    Alien (1979) DVD           fid=6
    Alien (1979) Blu-ray       fid=16880
    Alien (1979) Blu-ray 4K    fid=50198
    Aliens (1986) DVD          fid=11
    Aliens (1986) Blu-ray      fid=16881
    Aliens (1986) Blu-ray 4K   fid=67848
    Alien 3 (1992) DVD         fid=12
    Alien 3 (1992) Blu-ray     fid=16882

Note on blu-ray.com:
    blu-ray.com renders search results client-side via JavaScript.  The
    BlurayComClient.search() method returns empty results on current site
    versions.  Use BlurayComClient.get_edition_by_url() with a known direct
    URL instead.  The technical-spec scraping (codec, HDR, bitrate) works
    once you have a URL.
"""
from __future__ import annotations

import re
import time
from typing import List, Optional

import metadatarr.resolve.providers  # noqa: F401 — trigger provider self-registration

from metadatarr.client import DVDCompareClient
from metadatarr.models import DVDCompareEdition
from metadatarr.resolve import resolve
from metadatarr.resolve.entities import Role
from mediavocab import MediaType, VariantKind
from mediavocab.models.signals import Signals, compare_signals as compare, signal_hash

# ---------------------------------------------------------------------------
# Film metadata — known cuts and dvdcompare fids
# ---------------------------------------------------------------------------

FILMS = [
    {
        "title": "Alien",
        "year": 1979,
        "imdb": "tt0078748",
        "dvdcompare_fids": {
            "DVD": "6",
            "Blu-ray": "16880",
            "Blu-ray 4K": "50198",
        },
        "cuts": [
            ("Theatrical",    VariantKind.THEATRICAL, 117),
            ("Director's Cut", VariantKind.DIRECTORS,  116),
        ],
        "notes": [
            "Ridley Scott's Director's Cut (2003) is 1 min SHORTER, not longer.",
            "Scott trimmed pacing; he did not add new footage.",
        ],
    },
    {
        "title": "Aliens",
        "year": 1986,
        "imdb": "tt0090605",
        "dvdcompare_fids": {
            "DVD": "11",
            "Blu-ray": "16881",
            "Blu-ray 4K": "67848",
        },
        "cuts": [
            ("Theatrical",       VariantKind.THEATRICAL, 137),
            ("Special Edition",  VariantKind.EXTENDED,   154),
        ],
        "notes": [
            "Special Edition adds 17 min: colony scenes, sentry guns, Newt backstory.",
            "Widely considered the superior version by fans.",
        ],
    },
    {
        "title": "Alien 3",
        "year": 1992,
        "imdb": "tt0103644",
        "dvdcompare_fids": {
            "DVD": "12",
            "Blu-ray": "16882",
        },
        "cuts": [
            ("Theatrical",    VariantKind.THEATRICAL, 114),
            ("Assembly Cut",  VariantKind.EXTENDED,   144),
        ],
        "notes": [
            "The Assembly Cut is a 2003 restoration of the original workprint.",
            "David Fincher disowned BOTH versions; he had no final-cut rights.",
            "The Assembly Cut is NOT a director's cut — it is labelled 'extended'.",
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(title: str) -> None:
    print(f"\n{'=' * 64}")
    print(f"  {title}")
    print(f"{'=' * 64}")


def _section(title: str) -> None:
    print(f"\n--- {title} ---")


def _field(label: str, value, indent: int = 4) -> None:
    if value not in (None, [], ""):
        print(f"{' ' * indent}{label}: {value}")


def _short_title(raw: str) -> str:
    """Strip dvdcompare tab/whitespace padding from title strings."""
    return re.sub(r"\s+", " ", raw).strip()


# ---------------------------------------------------------------------------
# 1. Cut comparison using Signals + signal_hash
# ---------------------------------------------------------------------------

def section_cuts(film: dict) -> None:
    _section(f"Cut comparison (Signals)  —  {film['title']}")
    bags = []
    for name, variant, runtime_min in film["cuts"]:
        s = Signals(
            title=film["title"],
            year=film["year"],
            medium=MediaType.MOVIE,
            variant_kind=variant,
            runtime=float(runtime_min * 60),
        )
        bags.append((name, s))
        print(f"  [{name:<20}]  hash={signal_hash(s)[:12]}…  "
              f"runtime={runtime_min} min  variant={variant.value}")

    if len(bags) == 2:
        name_a, bag_a = bags[0]
        name_b, bag_b = bags[1]
        conflicts = compare(bag_a, bag_b)
        print(f"\n  compare({name_a!r}, {name_b!r})  →  "
              f"{len(conflicts)} conflict(s):")
        for c in conflicts:
            print(f"    {c.signal}: {c.ours!r}  ≠  {c.theirs!r}")
        if not conflicts:
            print("    (no conflicts — hashes differ only by variant_kind)")

    for note in film.get("notes", []):
        print(f"\n  Note: {note}")


# ---------------------------------------------------------------------------
# 2. dvdcompare.net — all known regional releases for a specific format
# ---------------------------------------------------------------------------

def section_dvdcompare(film: dict, client: DVDCompareClient, fmt: str = "Blu-ray") -> None:
    fid = film["dvdcompare_fids"].get(fmt)
    if not fid:
        print(f"  No {fmt} fid known for {film['title']}")
        return

    _section(f"dvdcompare.net {fmt}  —  {film['title']}  (fid={fid})")

    try:
        edition = client.get_edition_by_fid(fid)
    except Exception as exc:
        print(f"  get_edition failed: {exc}")
        return

    if not edition:
        print("  no data returned")
        return

    print(f"  {edition.title}")
    _field("url", edition.url)
    _field("imdb", edition.imdb_id)

    # Version / cut information — dvdcompare's core value
    if edition.version:
        print(f"\n  Versions present on disc(s):")
        print(f"    {edition.version}")
    if edition.cut_runtimes:
        print(f"\n  Cut runtimes:")
        for cr in edition.cut_runtimes:
            mins = f"{cr.runtime_seconds // 60} min" if cr.runtime_seconds else "?"
            print(f"    {cr.cut:<30}  {mins}")
    elif edition.version_differences:
        print(f"\n  CUTS section (runtime data):")
        for line in edition.version_differences.splitlines()[:8]:
            if line.strip():
                print(f"    {line.strip()}")

    # Structured per-release data (country, distributor, case, audio, subtitles)
    if edition.releases:
        print(f"\n  Regional releases ({len(edition.releases)} editions indexed):")
        for rel in edition.releases[:6]:
            country = rel.country or rel.region or "?"
            dist = (rel.distributor or "")[:28]
            ed = f" [{rel.edition_name}]" if rel.edition_name else ""
            print(f"    {country:<16}  {dist:<28}  {rel.case_type or '?'}{ed}")
        if len(edition.releases) > 6:
            print(f"    … and {len(edition.releases) - 6} more")


def section_dvdcompare_search(film: dict, client: DVDCompareClient) -> None:
    """Search dvdcompare and list all matching entries (title disambiguation)."""
    _section(f"dvdcompare.net search  —  {film['title']}")
    try:
        hits = client.search(film["title"])
    except Exception as exc:
        print(f"  search failed: {exc}")
        return

    # Filter to this film's year
    relevant = [
        h for h in hits
        if str(film["year"]) in h.title
    ]
    print(f"  Found {len(hits)} total, {len(relevant)} for {film['year']}:")
    for h in relevant[:8]:
        print(f"    fid={h.dvdcompare_id:<6}  {_short_title(h.title)}")


# ---------------------------------------------------------------------------
# 3. Fanedits via resolve() + include_variants
# ---------------------------------------------------------------------------

def section_fanedits(film: dict) -> None:
    _section(f"Fanedits (fanedit.org / IFDB)  —  {film['title']}")
    try:
        result = resolve(Signals(
            title=film["title"],
            year=film["year"],
            medium=MediaType.MOVIE,
            include_variants=True,
        ), max_workers=4)
    except Exception as exc:
        print(f"  resolve() failed: {exc}")
        return

    releases = result.relations.get(Role.RELEASE, [])
    fanedits = [r for r in releases if r.external_ids.fanedit_id]

    print(f"  resolver accepted: {[m.provider for m in result.accepted]}")
    ids = result.external_ids.model_dump(exclude_none=True)
    if ids:
        print(f"  external ids: {ids}")

    if not fanedits:
        print("  no fanedits indexed on IFDB for this title")
        return

    print(f"\n  {len(fanedits)} fanedit(s):")
    for fe in fanedits[:6]:
        print(f"\n    [{fe.external_ids.fanedit_id}] {fe.name}")
        url = (fe.external_ids.extra or {}).get("fanedit_url") or \
              (fe.external_ids.extra or {}).get("ifdb_url")
        _field("url", url, indent=6)
        if fe.signals:
            if fe.signals.variant_kind:
                _field("variant", fe.signals.variant_kind.value, indent=6)
            if fe.signals.runtime:
                _field("runtime", f"{int(fe.signals.runtime // 60)} min", indent=6)
            if fe.signals.edition:
                _field("edition", fe.signals.edition, indent=6)

    if len(fanedits) > 6:
        print(f"\n    … and {len(fanedits) - 6} more")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    dvdcompare = DVDCompareClient()

    for film in FILMS:
        _banner(f"{film['title']}  ({film['year']})")

        section_cuts(film)

        # dvdcompare search — shows all entries in their database for this title
        section_dvdcompare_search(film, dvdcompare)
        time.sleep(1)

        # dvdcompare detail — fetch the Blu-ray comparison page (all regional releases)
        section_dvdcompare(film, dvdcompare, fmt="Blu-ray")
        time.sleep(1)

        # Fanedits from IFDB
        section_fanedits(film)

    # -----------------------------------------------------------------------
    # Cross-film summary
    # -----------------------------------------------------------------------
    _banner("Cross-film cut summary")
    print()
    print(f"  {'Title':<12}  {'Cut':<22}  {'Runtime':>8}  {'VariantKind':<20}  Hash (12 chars)")
    print(f"  {'-'*12}  {'-'*22}  {'-'*8}  {'-'*20}  {'-'*12}")
    for film in FILMS:
        for name, variant, runtime_min in film["cuts"]:
            s = Signals(
                title=film["title"],
                year=film["year"],
                medium=MediaType.MOVIE,
                variant_kind=variant,
                runtime=float(runtime_min * 60),
            )
            print(f"  {film['title']:<12}  {name:<22}  {runtime_min:>6} min  "
                  f"{variant.value:<20}  {signal_hash(s)[:12]}")

    _section("dvdcompare.net film IDs — Alien trilogy")
    print()
    for film in FILMS:
        for fmt, fid in film["dvdcompare_fids"].items():
            url = f"https://www.dvdcompare.net/comparisons/film.php?fid={fid}"
            print(f"  {film['title']:<10}  {fmt:<12}  fid={fid:<6}  {url}")

    _section("Director notes")
    print()
    for film in FILMS:
        for note in film["notes"]:
            print(f"  [{film['title']}] {note}")

    print()


if __name__ == "__main__":
    main()
