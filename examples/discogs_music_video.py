"""Discogs for music video LaserDiscs and soundtrack vinyl research.

Discogs is a **music database**.  It is the authoritative source for:
  - Music video LaserDiscs (concert films, live performances)
  - Official music video compilations on VHS / DVD
  - Soundtrack albums on vinyl, CD, and cassette
  - Physical release metadata: NTSC/PAL, CLV/CAV, barcodes, matrix numbers,
    catalogue numbers, community have/want counts

It has sparse-to-zero coverage of **narrative feature films**.
For feature film disc research use dvdcompare.net (see physical_disc_verify.py).

User story: "I collect music video LaserDiscs and soundtrack vinyl. I want to
find every regional pressing of a concert film, see NTSC vs PAL in the format
details, check how many collectors own each pressing, and verify barcodes."

What this script demonstrates:
  1. search_video() — concert film LaserDisc search with automatic music
     genre filtering; shows the contrast with the raw search() output
  2. get_release() — full structured data: format_details (NTSC/PAL, CLV/CAV),
     identifiers (barcode, matrix), community stats (have/want/rating)
  3. search() for soundtrack vinyl — plain audio format search, no filter needed
  4. get_master() + get_master_versions() — all regional pressings of a title
  5. Medium.MUSIC_VIDEO in Signals — how to model music videos for the resolver

No authentication required.  Discogs enforces 60 req/min with a token,
25 req/min without.  The client adds a 2.5-second sleep automatically.

Known Discogs IDs used:
    release/1383918  — Ministry 'In Case You Didn't Feel Like Showing Up (Live)'
                       Concert film on Laserdisc; NTSC, CLV, Lumivision 1991
                       This is the same fixture used in tests/test_physical_clients.py
"""
from __future__ import annotations

import time
from typing import List, Optional

from metadatarr.client import DiscogsClient
from metadatarr.models import DiscogsRelease, DiscogsSearchHit
from metadatarr.resolve.signals import Medium, Signals


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
    if value not in (None, [], "", 0):
        print(f"{' ' * indent}{label}: {value}")


# ---------------------------------------------------------------------------
# 1. Genre filter contrast — what search_video() does that search() does not
# ---------------------------------------------------------------------------

def section_contrast(client: DiscogsClient) -> None:
    """Demonstrate the music-exclusion filter.

    Ministry's concert LaserDisc is tagged BOTH 'Electronic, Rock' AND
    'Non-Music, Stage & Screen'.  Server-side genre=Non-Music doesn't exclude
    it.  search_video() applies a client-side _DISCOGS_MUSIC_GENRES check and
    correctly filters it out — Ministry is a band, not a standalone film.
    """
    _section("Genre filter contrast: search() vs search_video() — 'Ministry'")

    print("  search('Ministry', fmt='Laserdisc', genre=None) — no filter:")
    raw = client.search("Ministry", fmt="Laserdisc", genre=None, per_page=5)
    for h in raw[:5]:
        genre_str = ", ".join(h.genre) if h.genre else "—"
        print(f"    [{h.id}]  {h.title!r}")
        print(f"            genres: {genre_str}")
    if not raw:
        print("    (no results)")

    time.sleep(2.5)

    print("\n  search_video('Ministry', fmt='Laserdisc') — music filter active:")
    filtered = client.search_video("Ministry", fmt="Laserdisc", per_page=5)
    if filtered:
        for h in filtered[:5]:
            print(f"    [{h.id}]  {h.title!r}  genres={', '.join(h.genre)}")
    else:
        print("    (no results — Ministry is a music act; all releases filtered out)")
        print("    Correct: search_video() is for standalone concert films, not band promos.")


# ---------------------------------------------------------------------------
# 2. Concert film LaserDisc — search and detail
# ---------------------------------------------------------------------------

def section_concert_search(query: str, client: DiscogsClient) -> List[DiscogsSearchHit]:
    _section(f"search_video({query!r}, fmt='Laserdisc')")
    hits = client.search_video(query, fmt="Laserdisc", per_page=6)

    if not hits:
        print(f"  no results for {query!r}")
        return []

    print(f"  {len(hits)} result(s):")
    for h in hits[:6]:
        label_str = ", ".join(h.label[:2]) if h.label else "—"
        genre_str = ", ".join(h.genre[:3]) if h.genre else "—"
        print(f"\n  [{h.id}]  {h.title}  ({h.year or '?'})")
        print(f"         country: {h.country or '?'}")
        print(f"         label  : {label_str}")
        print(f"         genres : {genre_str}")

    return hits


def section_release_detail(release_id: int, label: str, client: DiscogsClient) -> Optional[DiscogsRelease]:
    _section(f"get_release({release_id}) — {label}")
    try:
        rel = client.get_release(release_id)
    except Exception as exc:
        print(f"  failed: {exc}")
        return None

    if not rel:
        print("  no data returned")
        return None

    print(f"  title    : {rel.title}")
    _field("released", rel.released or str(rel.year))
    _field("labels", ", ".join(rel.label_names[:3]))
    _field("formats", ", ".join(rel.format_names))
    _field("country", rel.country)
    _field("genres", ", ".join(rel.genres[:5]))

    # Format details — NTSC/PAL, CLV/CAV are in fd.descriptions
    if rel.format_details:
        print(f"\n  Format details:")
        for fd in rel.format_details:
            detail = " · ".join(fd.descriptions) if fd.descriptions else "(no detail)"
            qty = f"  qty={fd.qty}" if fd.qty and fd.qty != 1 else ""
            note = f"  [{fd.text}]" if fd.text else ""
            print(f"    {fd.name:<14}  {detail}{qty}{note}")

    # Identifiers — barcode, matrix, catalog number
    if rel.identifiers:
        print(f"\n  Identifiers ({len(rel.identifiers)}):")
        for ident in rel.identifiers[:8]:
            print(f"    {ident.type:<22}  {ident.value}")

    # Community stats
    if rel.community:
        c = rel.community
        rating = (f"{c.rating_average:.2f}/5 ({c.rating_count} ratings)"
                  if c.rating_average else "no ratings")
        print(f"\n  Community:  have={c.have}  want={c.want}  {rating}")

    _field("cover", rel.primary_image_url)
    _field("master_id", rel.master_id)

    return rel


# ---------------------------------------------------------------------------
# 3. Master record + all pressings
# ---------------------------------------------------------------------------

def section_master_versions(master_id: int, label: str, client: DiscogsClient) -> None:
    _section(f"get_master({master_id}) + get_master_versions() — {label}")
    try:
        master = client.get_master(master_id)
    except Exception as exc:
        print(f"  get_master failed: {exc}")
        return

    if not master:
        print("  no master data")
        return

    print(f"  title  : {master.get('title', '?')}")
    print(f"  year   : {master.get('year', '?')}")
    print(f"  main   : release/{master.get('main_release', '?')}")
    print(f"  total  : {master.get('versions_count', '?')} versions")

    try:
        versions = client.get_master_versions(master_id, per_page=10)
    except Exception as exc:
        print(f"  get_master_versions failed: {exc}")
        return

    if not versions:
        print("  (no versions returned)")
        return

    print(f"\n  First {len(versions)} pressing(s):")
    print(f"  {'ID':<10}  {'Country':<14}  {'Format':<22}  {'Label':<22}  Year")
    print(f"  {'-'*10}  {'-'*14}  {'-'*22}  {'-'*22}  ----")
    for v in versions[:10]:
        country = (v.get("country") or "?")[:12]
        fmt     = (v.get("format")  or "?")[:20]
        lbl     = (v.get("label")   or "?")[:20]
        year    = v.get("year") or "?"
        vid     = v.get("id") or "?"
        print(f"  {str(vid):<10}  {country:<14}  {fmt:<22}  {lbl:<22}  {year}")


# ---------------------------------------------------------------------------
# 4. Soundtrack vinyl — plain audio search (no video filter needed)
# ---------------------------------------------------------------------------

def section_soundtrack_vinyl(title: str, client: DiscogsClient) -> None:
    _section(f"search({title!r}, fmt='Vinyl') — soundtrack vinyl")
    hits = client.search(title, fmt="Vinyl", per_page=5)

    if not hits:
        print(f"  no vinyl results for {title!r}")
        return

    print(f"  {len(hits)} result(s):")
    for h in hits[:4]:
        label_str = ", ".join(h.label[:2]) if h.label else "—"
        genre_str = ", ".join(h.genre[:3]) if h.genre else "—"
        print(f"  [{h.id}]  {h.title}  ({h.year or '?'})")
        print(f"         label: {label_str}  country: {h.country or '?'}")
        print(f"         genres: {genre_str}")


# ---------------------------------------------------------------------------
# 5. Medium.MUSIC_VIDEO in Signals
# ---------------------------------------------------------------------------

def section_signals() -> None:
    _section("Medium.MUSIC_VIDEO in Signals (offline)")
    print("  Music videos are a distinct medium from audio tracks.")
    print("  Use Medium.MUSIC_VIDEO when resolving concert films or official MVs.\n")

    s = Signals(
        title="In Case You Didn't Feel Like Showing Up",
        artist="Ministry",
        year=1991,
        medium=Medium.MUSIC_VIDEO,
        source_format="Laserdisc",
        country="US",
    )
    print(f"  title         : {s.title}")
    print(f"  artist        : {s.artist}")
    print(f"  medium        : {s.medium.value!r}  ← Medium.MUSIC_VIDEO")
    print(f"  source_format : {s.source_format}")
    print(f"  country       : {s.country}")
    print(f"\n  The Discogs provider handles MUSIC_VIDEO (and MUSIC, OTHER).")
    print(f"  It does NOT handle MOVIE or TV — use dvdcompare/bluray.com for those.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    client = DiscogsClient()

    # 1. Show what the filter does
    _banner("Genre filter: search() vs search_video()")
    section_contrast(client)
    time.sleep(2.5)

    # 2. Known working release — Ministry concert film
    _banner("Concert film LaserDisc — Ministry (release/1383918)")
    rel = section_release_detail(
        1383918,
        "Ministry — In Case You Didn't Feel Like Showing Up (Live)",
        client,
    )
    time.sleep(2.5)

    # 3. All pressings via master record
    if rel and rel.master_id:
        _banner(f"All pressings — master/{rel.master_id}")
        section_master_versions(rel.master_id, rel.title or "Ministry LD", client)
        time.sleep(2.5)

    # 4. Concert film search — try known titles
    _banner("Concert film search — 'Stop Making Sense'")
    hits = section_concert_search("Stop Making Sense", client)
    time.sleep(2.5)
    if hits:
        section_release_detail(hits[0].id, hits[0].title, client)
        time.sleep(2.5)

    # 5. Soundtrack vinyl — Blade Runner (Vangelis; well-indexed on Discogs)
    _banner("Soundtrack vinyl — Blade Runner (Vangelis)")
    section_soundtrack_vinyl("Blade Runner", client)
    time.sleep(2.5)

    # 6. Medium.MUSIC_VIDEO — offline, no HTTP
    _banner("Signals: Medium.MUSIC_VIDEO")
    section_signals()

    print()


if __name__ == "__main__":
    main()
