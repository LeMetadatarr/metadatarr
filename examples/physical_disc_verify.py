"""Verify which cut of a film a physical disc contains using DVDCompare.

User story: "I just pulled a Blu-ray off my shelf. The sleeve says 'Blade
Runner' but doesn't say which version. I want to know: is this the Final Cut,
the Director's Cut, or the theatrical? And which regional edition is it — do
I have the UK collector's tin or the plain US release?"

This script shows how to:
  1. Look up a film on dvdcompare.net to get per-release cut metadata
  2. Map DVDCompare cut labels to Signals VariantKind
  3. Cross-reference physical release data (country, distributor, case type)
     to identify a specific regional edition
  4. Build a Signals bag for the confirmed disc so your library system gets
     the right canonical hash

The dvdcompare comparison pages carry the runtime for each cut on each disc —
that runtime is the most reliable way to confirm which version you have.

Requires no auth or extra install — DVDCompareClient ships with the base
package.
"""
from __future__ import annotations

import re
from typing import Optional

from metadatarr.client import DVDCompareClient
from metadatarr.models import DVDCompareRelease
from mediavocab import MediaType, VariantKind
from mediavocab.models.signals import Signals, signal_hash

# ---------------------------------------------------------------------------
# Known dvdcompare fids for Blade Runner Blu-ray releases
# ---------------------------------------------------------------------------
FILM = {
    "title": "Alien",
    "year": 1979,
    "imdb": "tt0078748",
    # fid=16880 is the Alien Blu-ray comparison page (all regional releases)
    # Run client.search("Alien") to find fids for other films.
    "bluray_fid": "16880",
}

# Map dvdcompare cut label substrings → VariantKind
# Order matters: more specific matches first
_CUT_LABEL_MAP = [
    ("final cut",       VariantKind.DIRECTORS),
    ("director",        VariantKind.DIRECTORS),
    ("international",   VariantKind.THEATRICAL),   # International = US theatrical
    ("theatrical",      VariantKind.THEATRICAL),
    ("workprint",       VariantKind.EXTENDED),
    ("extended",        VariantKind.EXTENDED),
    ("assembly",        VariantKind.EXTENDED),
]


def _infer_variant(cut_label: str) -> VariantKind:
    lower = cut_label.lower()
    for keyword, kind in _CUT_LABEL_MAP:
        if keyword in lower:
            return kind
    return VariantKind.THEATRICAL


def _runtime_secs(runtime_str: str) -> Optional[int]:
    """Parse 'h:mm:ss' or 'mm:ss' or bare minutes into seconds."""
    m = re.match(r"(\d+):(\d{2}):(\d{2})", runtime_str)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    m = re.match(r"(\d+):(\d{2})", runtime_str)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r"(\d+)", runtime_str)
    if m:
        return int(m.group(1)) * 60
    return None


def show_cut_runtimes(edition) -> None:
    """Print the cut runtimes dvdcompare found for this comparison page."""
    if not edition.cut_runtimes:
        print("  (no cut runtime data on this page)")
        return
    print(f"  {'Cut':<30}  Runtime")
    print(f"  {'-'*30}  -------")
    for cr in edition.cut_runtimes:
        mins = f"{cr.runtime_seconds // 60}:{cr.runtime_seconds % 60:02d}"
        print(f"  {cr.cut:<30}  {mins}")


def show_regional_releases(edition) -> None:
    """Print every regional release dvdcompare has on this page."""
    if not edition.releases:
        print("  (no per-release data parsed)")
        return
    print(f"\n  {'#':<4}  {'Country':<12}  {'Distributor':<22}  {'Edition':<22}  Case")
    print(f"  {'-'*4}  {'-'*12}  {'-'*22}  {'-'*22}  ----")
    for i, rel in enumerate(edition.releases, 1):
        country  = rel.country or rel.region or "?"
        dist     = (rel.distributor or "")[:20]
        ed       = (rel.edition_name or "")[:20]
        case     = rel.case_type or "?"
        print(f"  {i:<4}  {country:<12}  {dist:<22}  {ed:<22}  {case}")


def identify_disc(edition, country_hint: str) -> Optional[DVDCompareRelease]:
    """Find the best matching release for a given country."""
    country_lower = country_hint.lower()
    for rel in edition.releases:
        haystack = " ".join([
            rel.country or "", rel.region or "", rel.distributor or "",
        ]).lower()
        if country_lower in haystack:
            return rel
    return None


def build_signals(film: dict, cut_label: str, runtime_secs: Optional[int],
                  region: Optional[str]) -> Signals:
    variant = _infer_variant(cut_label)
    return Signals(
        title=film["title"],
        year=film["year"],
        medium=MediaType.MOVIE,
        variant_kind=variant,
        runtime=float(runtime_secs) if runtime_secs else None,
        source_format="Blu-ray",
        region=region,
    )


def main() -> None:
    client = DVDCompareClient()

    print(f"Looking up {FILM['title']} ({FILM['year']}) on dvdcompare.net…")
    edition = client.get_edition_by_fid(FILM["bluray_fid"])
    if not edition:
        print("  No data returned — check fid or network.")
        return

    print(f"\n  {edition.title}")
    print(f"  url  : {edition.url}")
    print(f"  imdb : {edition.imdb_id}")

    # -----------------------------------------------------------------------
    # 1. What cuts does this Blu-ray carry?
    # -----------------------------------------------------------------------
    print("\n--- Cuts present on disc ---")
    show_cut_runtimes(edition)

    # -----------------------------------------------------------------------
    # 2. What regional releases are there?
    # -----------------------------------------------------------------------
    print("\n--- Regional releases indexed ---")
    show_regional_releases(edition)

    # -----------------------------------------------------------------------
    # 3. Identify a specific disc by country
    # -----------------------------------------------------------------------
    # Simulate: "I have a UK release" — dvdcompare uses "United Kingdom"
    COUNTRY_HINT = "United Kingdom"
    print(f"\n--- Identifying {COUNTRY_HINT} release ---")
    rel = identify_disc(edition, COUNTRY_HINT)
    if rel:
        print(f"  Found: country={rel.country}  distributor={rel.distributor}")
        print(f"         edition={rel.edition_name}  case={rel.case_type}")
        print(f"         aspect_ratio={rel.aspect_ratio}  picture={rel.picture_format}")
        if rel.soundtrack:
            print(f"         soundtracks: {', '.join(rel.soundtrack[:4])}")
        if rel.subtitles:
            print(f"         subtitles: {', '.join(rel.subtitles[:6])}")
    else:
        print(f"  No {COUNTRY_HINT} release found on this page.")
        rel = edition.releases[0] if edition.releases else None

    # -----------------------------------------------------------------------
    # 4. Build a Signals bag for the confirmed disc
    # -----------------------------------------------------------------------
    print("\n--- Signals bag for the confirmed disc ---")

    # Use the first cut runtime (usually the main cut on the disc)
    if edition.cut_runtimes:
        best_cut = edition.cut_runtimes[0]
        cut_label = best_cut.cut
        runtime_s = best_cut.runtime_seconds
    else:
        cut_label, runtime_s = "Final Cut", None

    region = rel.region or rel.country if rel else None
    sig = build_signals(FILM, cut_label, runtime_s, region)

    print(f"  title        : {sig.title}")
    print(f"  year         : {sig.year}")
    print(f"  variant_kind : {sig.variant_kind.value if sig.variant_kind else None}")
    print(f"  runtime      : {int(sig.runtime // 60)} min" if sig.runtime else "  runtime      : unknown")
    print(f"  source_format: {sig.source_format}")
    print(f"  region       : {sig.region}")
    print(f"\n  canonical hash: {signal_hash(sig)}")
    print()


if __name__ == "__main__":
    main()
