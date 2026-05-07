"""YouTube Music metadata provider via :mod:`tutubo` (optional dep).

YouTube Music is conceptually distinct from regular YouTube: it has a
catalog of *entities* — artists, albums, playlists — each with a stable
``browseId`` (e.g. ``UCxxx…`` for artist channels, ``MPREb_xxx`` for
release-group entities, ``OLAK5uy_…`` for album playlists). Those
browseIds are canonical music IDs, not upload references, so they're
safe to treat as :attr:`ExternalIds` cross-references.

Track-level results still carry a YouTube ``videoId`` because every
playable item is ultimately an upload — but we surface it under
``youtube_music_video_id`` rather than the regular ``youtube_video_id``
key, to make the conceptual boundary explicit. A consumer that
deduplicates "the same recording across providers" should treat
``youtube_music_video_id`` as a *recording* reference, not a *work* one;
the canonical work-level cross-reference is the artist + album
browseIds.

Keys written to :attr:`ExternalIds.extra`:

- ``youtube_music_video_id``           — track-level (the YT Music master)
- ``youtube_music_artist_browse_id``   — canonical artist entity id
- ``youtube_music_album_browse_id``    — canonical album entity id
- ``youtube_music_playlist_id``        — ``audioPlaylistId`` for the album
"""
from __future__ import annotations

import logging
from typing import Optional

from tutubo import search_yt_music

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType, PlaybackModality
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.youtube_music")


def _safe_year(value) -> Optional[int]:
    if value is None:
        return None
    text = str(value)
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else None


def _first_artist(top: dict) -> tuple[Optional[str], Optional[str]]:
    """Return ``(name, browse_id)`` for the first artist on a YT Music result.

    Prefers tutubo's first-class ``artistBrowseId`` field (added in tutubo
    >= the version that exposes browseIds as properties); falls back to
    the nested raw form for older / mixed payloads.
    """
    browse = top.get("artistBrowseId")
    artists = top.get("artists")
    if isinstance(artists, list) and artists:
        a = artists[0] or {}
        if isinstance(a, dict):
            return (a.get("name"),
                    browse or a.get("id") or a.get("browseId"))
    name = top.get("artist")
    return (str(name) if name else None), browse or None


def _album_ids(top: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return ``(album_name, browse_id, audio_playlist_id)``."""
    raw = top.get("album")
    browse = top.get("albumBrowseId")
    name = playlist_id = None
    if isinstance(raw, dict):
        name = raw.get("name")
        browse = browse or raw.get("id") or raw.get("browseId")
    elif isinstance(raw, str):
        name = raw
    playlist_id = top.get("audioPlaylistId") or top.get("playlistId")
    return name, browse, playlist_id


class YouTubeMusicProvider(MetadataProvider):
    name = "youtube_music"
    media = {MediaType.MUSIC}
    modality = {PlaybackModality.AUDIO}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium and signals.medium != MediaType.MUSIC:
            return None

        try:
            query = f"{signals.artist} {signals.title}" if signals.artist else signals.title
            results = list(search_yt_music(query, as_dict=True))
        except Exception as exc:
            LOG.warning("youtube_music search failed: %s", exc)
            return None

        if not results:
            return None
        top = results[0]

        title = top.get("title") or signals.title
        video_id = top.get("videoId") or top.get("video_id")
        artist_name, artist_browse = _first_artist(top)
        album_name, album_browse, album_playlist = _album_ids(top)

        runtime = top.get("duration") or top.get("length")
        try:
            runtime = float(runtime) if runtime is not None else None
        except (TypeError, ValueError):
            runtime = None

        extra: dict = {}
        if video_id:
            extra["youtube_music_video_id"] = str(video_id)
        if artist_browse:
            extra["youtube_music_artist_browse_id"] = str(artist_browse)
        if album_browse:
            extra["youtube_music_album_browse_id"] = str(album_browse)
        if album_playlist:
            extra["youtube_music_playlist_id"] = str(album_playlist)

        relations: dict = {}
        if artist_name:
            artist_extra: dict = {}
            if artist_browse:
                artist_extra["youtube_music_artist_browse_id"] = str(artist_browse)
            relations[EntityRole.ARTIST] = [ProviderEntity(
        role=EntityRole.ARTIST,
                name=artist_name,
                external_ids=ExternalIds(extra=artist_extra),
            )]
        if album_name:
            if album_browse:
                extra["youtube_music_album_browse_id"] = str(album_browse)
            if album_playlist:
                extra["youtube_music_playlist_id"] = str(album_playlist)

        return ProviderMatch(
            provider=self.name,
            confidence=0.7,
            signals=Signals(
                title=title,
                artist=artist_name,
                year=_safe_year(top.get("year")),
                runtime=runtime,
                medium=MediaType.MUSIC,
            ),
            external_ids=ExternalIds(extra=extra),
            relations=relations,
        )


register(YouTubeMusicProvider())
