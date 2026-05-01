"""Resolve a music track and collect every playable stream URL.

User story: I want to play *"Get Lucky"* by Daft Punk right now.  I don't
care which platform — give me every URL I can hand to a player.

The resolver fans out to all active music providers.  Any that find the
track emit a playable URL into ``external_ids.extra``.  ``ExternalIds.streams``
aggregates those into a typed list of :class:`~metadatarr.models.Stream`
objects, one per platform.  The caller can then pick by ``platform`` or
``media_type``, or just take the first result.

Platform coverage (install the optional extras you want):

    pip install metadatarr[soundcloud,bandcamp,youtube]

Without any extras installed, only providers that need no optional deps
(AudioDB music-video URL, …) will contribute.

Run it::

    python examples/streams_music.py
    python examples/streams_music.py "Harder Better Faster Stronger" "Daft Punk"
"""
from __future__ import annotations

import sys

from metadatarr.resolve import Medium, Signals, active_providers, consolidate, search


TITLE  = "Get Lucky"
ARTIST = "Daft Punk"


def _banner(title: str, artist: str) -> None:
    print("=" * 70)
    print(f"  Streams for: {artist} — {title}")
    print("=" * 70)


def _print_providers() -> None:
    music_providers = [p.name for p in active_providers(medium=Medium.MUSIC)]
    print(f"  active music providers: {', '.join(music_providers) or '(none)'}")


def _resolve_streams(title: str, artist: str):
    sig = Signals(title=title, artist=artist, medium=Medium.MUSIC)
    candidates = search(sig)
    if not candidates:
        return None
    return consolidate(candidates, local=sig)


def main() -> None:
    args   = sys.argv[1:]
    title  = args[0] if args else TITLE
    artist = args[1] if len(args) > 1 else ARTIST

    _banner(title, artist)
    _print_providers()

    result = _resolve_streams(title, artist)
    if result is None:
        print("\n  No providers returned a match.")
        print("  Install streaming extras:  pip install metadatarr[soundcloud,bandcamp,youtube]")
        return

    streams = result.external_ids.streams

    if not streams:
        print("\n  No playable streams found for this track.")
        print("  (Providers may have matched but found no track-level playable URL.)")
        ids = result.external_ids.model_dump(exclude_none=True)
        ids.pop("extra", None)
        print(f"  resolved IDs: {ids}")
        return

    print(f"\n  Found {len(streams)} playable stream(s):\n")
    print(f"  {'Platform':<16}  {'Type':<10}  URL")
    print(f"  {'-'*16}  {'-'*10}  {'-'*42}")
    for s in streams:
        print(f"  {s.platform:<16}  {s.media_type:<10}  {s.url}")

    # --- filter examples ---
    sc = [s for s in streams if s.platform == "soundcloud"]
    if sc:
        print(f"\n  SoundCloud URL (ready for player): {sc[0].url}")

    yt = [s for s in streams if s.platform in ("youtube", "youtube_music")]
    if yt:
        print(f"  YouTube URL:                       {yt[0].url}")


if __name__ == "__main__":
    main()
