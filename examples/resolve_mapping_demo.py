"""Cross-platform track resolution — search-time, with only an artist mapping.

The package ships a *single* artist-level identity assertion in
``/metadatarr/data/mappings.toml``::

    [[artist]]
    name = "Acidkid / Piratech"
    soundcloud_artist_url = "https://soundcloud.com/acidkid"
    bandcamp_artist_url   = "https://piratech.bandcamp.com/"

Track-level URL pairs are NOT in the TOML. They are derived at search
time using a three-step pattern:

1. **Search the platform you started on** — here we hand the resolver
   a ``Signals(title=…, artist=…)`` and let the SoundCloud provider
   surface ``soundcloud_track_url`` + ``soundcloud_artist_url``.
2. **Apply the artist mapping** — ``consolidate()`` runs
   ``apply_mappings(EntityKind.ARTIST, …)`` for every accepted match,
   which fills in ``bandcamp_artist_url`` from the curated TOML row.
3. **Slug the title against the linked artist's domain** — Bandcamp's
   track URLs follow ``<artist_url>/track/<slug>``; we synthesise the
   candidate slug from the title and confirm it exists with a HEAD
   request via ``derive_track_url`` + ``confirm_track_url``.

The end result: both the SoundCloud track URL and the Bandcamp track URL
are known for every track, even though the only static link declared in
the package is the artist-level pair.

Tracks demoed:

- *Piratech — Nuclear Chill*
- *Piratech — Don't Explain*

Run it::

    pip install metadatarr[bandcamp,soundcloud]
    python examples/resolve_mapping_demo.py
"""
from __future__ import annotations

from typing import Optional

from metadatarr.resolve import (
    ExternalIds,
    MediaType,
    Signals,
    active_providers,
    consolidate,
)
from metadatarr.resolve.providers.bandcamp import (
    confirm_track_url,
    derive_track_url,
)


TRACKS = (
    "Nuclear Chill",
    "Don't Explain",
)
ARTIST = "Piratech"


def _resolve_one(track_title: str, soundcloud_provider) -> dict:
    """Run the three-step resolution for a single track. Returns the
    final ``extra`` dict so the caller can pretty-print + diff."""
    sig = Signals(title=track_title, artist=ARTIST, medium=MediaType.MUSIC)

    # Step 1: search SoundCloud.
    sc_match = soundcloud_provider.lookup(sig)
    if sc_match is None:
        return {}

    # Step 2: consolidate runs apply_mappings(ARTIST, …) and back-fills
    # bandcamp_artist_url from the curated TOML row.
    result = consolidate([sc_match], local=sig)
    extras = dict(result.external_ids.extra)

    # Step 3: derive a Bandcamp track URL from the linked artist URL +
    # the title, then HEAD-probe to confirm.
    bc_artist_url = extras.get("bandcamp_artist_url")
    if bc_artist_url:
        candidate = derive_track_url(bc_artist_url, track_title)
        if candidate and confirm_track_url(candidate):
            extras["bandcamp_track_url"] = candidate
            extras["bandcamp_track_url_origin"] = "derived+head-confirmed"
    return extras


def _print_resolved(track: str, extras: dict) -> None:
    print(f"\n  {ARTIST} — {track}")
    if not extras:
        print("    (no SoundCloud match — abandoning)")
        return
    pairs = [
        ("soundcloud_track_url",  extras.get("soundcloud_track_url")),
        ("soundcloud_artist_url", extras.get("soundcloud_artist_url")),
        ("bandcamp_artist_url",   extras.get("bandcamp_artist_url")),
        ("bandcamp_track_url",    extras.get("bandcamp_track_url")),
    ]
    for key, val in pairs:
        marker = "✓" if val else "✗"
        print(f"    {marker}  {key:<22} = {val}")
    if extras.get("bandcamp_track_url_origin"):
        print(f"    ℹ  bandcamp_track_url derived via "
              f"{extras['bandcamp_track_url_origin']}")


def main() -> None:
    print("=" * 78)
    print("  Cross-platform track resolution — derive at search time")
    print("=" * 78)

    available = {p.name: p for p in active_providers(medium=MediaType.MUSIC)}
    soundcloud = available.get("soundcloud")
    if soundcloud is None:
        print("\nThe SoundCloud provider is not active. Install it with:")
        print("  pip install metadatarr[soundcloud]")
        return

    for track in TRACKS:
        extras = _resolve_one(track, soundcloud)
        _print_resolved(track, extras)


if __name__ == "__main__":
    main()
