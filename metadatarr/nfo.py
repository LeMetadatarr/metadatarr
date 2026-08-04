# SPDX-License-Identifier: Apache-2.0
"""Kodi/Jellyfin ``.nfo`` sidecar generation.

Jellyfin (and Kodi) read a ``.nfo`` file sitting next to a media file to
fill in rich metadata instead of relying on filename scraping or a live
network lookup. This module builds that XML — **metadata only**: it never
downloads the thumbnail, it just writes the URL into ``<thumb>`` and lets
Jellyfin fetch it itself.

Three root elements are used, matching Jellyfin's NFO support:

* ``<movie>`` for non-episodic video
* ``<episodedetails>`` for a TV/episodic-series episode (season/episode set)
* ``<musicvideo>`` for music

This lives in metadatarr because NFO generation is metadata representation:
mapping a resolved :class:`~mediavocab.models.ExternalIds` + signal bag into
the on-disk format a media server understands.
"""
from __future__ import annotations

from typing import Iterable, Optional
from xml.sax.saxutils import escape

from mediavocab.models import ExternalIds

# ExternalIds field -> Kodi/Jellyfin <uniqueid type="..."> value.
_UNIQUEID_TYPES = {
    "imdb": "imdb",
    "tmdb_movie": "tmdb",
    "tmdb_tv": "tmdb",
    "tvdb": "tvdb",
    "tvmaze": "tvmaze",
    "trakt_id": "trakt",
    "musicbrainz_recording": "musicbrainz_recording",
    "musicbrainz_release": "musicbrainz_release",
    "musicbrainz_release_group": "musicbrainz_release_group",
    "musicbrainz_artist": "musicbrainz_artist",
}


def _tag(name: str, value) -> str:
    return f"  <{name}>{escape(str(value))}</{name}>"


def _runtime_minutes(runtime: Optional[float]) -> Optional[int]:
    if not runtime or runtime <= 0:
        return None
    minutes = round(runtime / 60)
    return minutes if minutes > 0 else 1


def nfo_xml(
    *,
    title: str,
    year: Optional[int] = None,
    media_kind: str = "movie",
    external_ids: Optional[ExternalIds] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
    plot: Optional[str] = None,
    runtime: Optional[float] = None,
    thumbnail: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> str:
    """Build a well-formed Kodi/Jellyfin-compatible NFO XML string.

    ``media_kind`` is one of ``"movie"``, ``"music"``, ``"episodic"`` — it
    selects the root element together with ``season``/``episode`` (an
    episodic kind with season and/or episode set emits ``<episodedetails>``;
    without season/episode it falls back to ``<movie>``).
    """
    is_music = media_kind == "music"
    is_episode = media_kind == "episodic" and (season is not None or episode is not None)

    if is_music:
        root = "musicvideo"
    elif is_episode:
        root = "episodedetails"
    else:
        root = "movie"

    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', f"<{root}>"]
    lines.append(_tag("title", title))
    if plot:
        lines.append(_tag("plot", plot))

    if is_music and artist:
        lines.append(_tag("artist", artist))
    if is_music and album:
        lines.append(_tag("album", album))
    if not is_music and artist:
        lines.append(_tag("studio", artist))

    if is_episode:
        if season is not None:
            lines.append(_tag("season", season))
        if episode is not None:
            lines.append(_tag("episode", episode))

    for t in tags or ():
        lines.append(_tag("genre", t))
        lines.append(_tag("tag", t))

    minutes = _runtime_minutes(runtime)
    if minutes is not None:
        lines.append(_tag("runtime", minutes))

    if thumbnail:
        lines.append(_tag("thumb", thumbnail))

    if year:
        lines.append(_tag("year", year))

    if not is_music and external_ids is not None:
        for field, value in external_ids.model_dump().items():
            if not value or field == "extra":
                continue
            uid_type = _UNIQUEID_TYPES.get(field)
            if not uid_type:
                continue
            lines.append(
                f'  <uniqueid type="{escape(uid_type)}">{escape(str(value))}</uniqueid>'
            )

    lines.append(f"</{root}>")
    return "\n".join(lines) + "\n"
