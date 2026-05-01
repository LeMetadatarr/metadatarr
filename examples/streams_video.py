"""Resolve a film or episode and get its YouTube playable URL.

User story: I want a YouTube URL I can pass directly to yt-dlp, mpv, or
any other player for a movie or podcast episode.

The YouTube provider runs on ``Medium.MOVIE``, ``Medium.TV``,
``Medium.PODCAST``, and ``Medium.OTHER`` (it deliberately skips
``Medium.MUSIC`` to avoid polluting music resolves with video noise).
It emits ``youtube_video_id`` (the upload ID) and ``youtube_channel_id``
into ``ExternalIds.extra``.  ``ExternalIds.streams`` constructs the full
``https://www.youtube.com/watch?v=<id>`` URL for you.

Requirements::

    pip install metadatarr

Run it::

    python examples/streams_video.py
    python examples/streams_video.py "Alien" movie
    python examples/streams_video.py "Hardcore History" podcast
"""
from __future__ import annotations

import sys

from metadatarr.resolve import Medium, Signals, active_providers, consolidate, search

_MEDIUM_MAP = {
    "movie":   Medium.MOVIE,
    "tv":      Medium.TV,
    "podcast": Medium.PODCAST,
    "other":   Medium.OTHER,
}

DEMOS = [
    ("Alien",              Medium.MOVIE),
    ("Hardcore History",   Medium.PODCAST),
]


def _resolve_youtube_url(title: str, medium: Medium) -> list:
    sig = Signals(title=title, medium=medium)
    candidates = search(sig)
    if not candidates:
        return []
    result = consolidate(candidates, local=sig)
    return [s for s in result.external_ids.streams
            if s.platform in ("youtube", "youtube_music")]


def _run(title: str, medium: Medium) -> None:
    print(f"\n  [{medium.value}]  {title}")
    streams = _resolve_youtube_url(title, medium)
    if not streams:
        print("    no YouTube stream found")
        return
    for s in streams:
        print(f"    {s.platform:<14}  {s.media_type:<8}  {s.url}")
        if s.id:
            print(f"    {'':14}  raw id: {s.id}")
        # Ready to hand to a player:
        print(f"    ▶  mpv \"{s.url}\"")


def main() -> None:
    print("=" * 70)
    print("  YouTube stream URL from title resolve")
    print("=" * 70)

    yt_providers = [p.name for p in active_providers()
                    if p.name in ("youtube", "youtube_music")]
    print(f"\n  active YouTube providers: {', '.join(yt_providers)}")

    if len(sys.argv) >= 2:
        title  = sys.argv[1]
        medium = _MEDIUM_MAP.get((sys.argv[2] if len(sys.argv) > 2 else "movie").lower(),
                                 Medium.MOVIE)
        _run(title, medium)
    else:
        for title, medium in DEMOS:
            _run(title, medium)


if __name__ == "__main__":
    main()
