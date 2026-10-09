"""Declare internet radio stations in mappings.toml, then retrieve stream URLs.

User story: I maintain a list of internet radio stations.  I want to declare
them once (in ``~/.config/metadatarr/mappings.toml``) and retrieve their
stream URLs at runtime the same way I retrieve any other playable content —
via ``ExternalIds.streams``.

How it works
------------
Any entity section in mappings.toml can carry a ``stream_url`` key.
Metadatarr treats it as a URL-type identifier (normalised, deduplicated
through the same index as Bandcamp/SoundCloud URLs) and stores it in
``ExternalIds.extra["stream_url"]``.  When you call ``.streams`` on that
``ExternalIds`` instance the entry surfaces as::

    Stream(platform="radio", media_type="stream", url="https://…")

Example mappings.toml entry
---------------------------
Add this to ``~/.config/metadatarr/mappings.toml`` (create it if it doesn't
exist)::

    [[channel]]
    name    = "WNYC FM 93.9"
    wikidata = "Q1123265"
    stream_url = "https://fm939.wnyc.org/wnycfm.aac"

    [[channel]]
    name    = "NTS Radio 1"
    stream_url = "https://stream-relay-geo.ntslive.net/stream"

    [[channel]]
    name    = "SomaFM Groove Salad"
    stream_url = "https://ice2.somafm.com/groovesalad-128-mp3"

This script demonstrates the pattern without requiring a live mappings file
by building ``MappingEntry`` objects directly — the same objects ``_load_file``
creates when it reads your TOML.

Run it::

    python examples/streams_radio.py
"""
from __future__ import annotations

from metadatarr.resolve.entities import EntityRole
from metadatarr.resolve.mappings import MappingEntry

# ---------------------------------------------------------------------------
# Demo stations — same structure _load_file produces from mappings.toml
# ---------------------------------------------------------------------------
STATIONS = [
    MappingEntry(
        role=EntityRole.CHANNEL,
        name="WNYC FM 93.9",
        identifiers={
            "wikidata":   "Q1123265",
            "stream_url": "https://fm939.wnyc.org/wnycfm.aac",
        },
    ),
    MappingEntry(
        role=EntityRole.CHANNEL,
        name="NTS Radio 1",
        identifiers={
            "stream_url": "https://stream-relay-geo.ntslive.net/stream",
        },
    ),
    MappingEntry(
        role=EntityRole.CHANNEL,
        name="SomaFM Groove Salad",
        identifiers={
            "stream_url": "https://ice2.somafm.com/groovesalad-128-mp3",
        },
    ),
    MappingEntry(
        role=EntityRole.CHANNEL,
        name="BBC Radio 6 Music",
        identifiers={
            "wikidata":   "Q1072120",
            "stream_url": "https://stream.live.vc.bbcmedia.co.uk/bbc_6music",
        },
    ),
]


def main() -> None:
    print("=" * 70)
    print("  Internet radio stations via mappings → ExternalIds.streams")
    print("=" * 70)
    print()
    print(f"  {'Station':<28}  Stream URL")
    print(f"  {'-'*28}  {'-'*38}")

    for station in STATIONS:
        ids     = station.to_external_ids()
        streams = ids.streams

        # .streams returns only playable entries — stream_url → Stream(radio, stream)
        radio = [s for s in streams if s.platform == "radio"]

        if radio:
            print(f"  {station.name:<28}  {radio[0].url}")
        else:
            print(f"  {station.name:<28}  (no stream_url declared)")

    # --- show how to build a play queue from the global store ---
    print()
    print("  Play queue (any station with a stream_url in the store):")
    print()
    queue = []
    for station in STATIONS:
        ids = station.to_external_ids()
        for s in ids.streams:
            if s.platform == "radio":
                queue.append((station.name, s.url))

    for i, (name, url) in enumerate(queue, start=1):
        print(f"  {i}. {name}")
        print(f"     ▶  mpv \"{url}\"")
        print()

    print("  Tip: add stations to ~/.config/metadatarr/mappings.toml")
    print("  and they will be auto-loaded by get_store() at runtime.")


if __name__ == "__main__":
    main()
