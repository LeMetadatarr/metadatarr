# SPDX-License-Identifier: Apache-2.0
"""Audio fingerprint identification ("Shazam"), then resolve/enrich to the
full cross-catalog id set.

Uses the LeMetadatarr ``xazam`` client (built on ``shazamio_core``) to
identify a track from raw audio bytes, then feeds the recognized
title/artist through :func:`metadatarr.resolve.base.resolve` (and any
ids it exposes through :func:`metadatarr.resolve.base.enrich`) so a Shazam
hit becomes a full MusicBrainz / Discogs / AudioDB record, not just a
title/artist guess.

``xazam`` is an optional dependency (install with
``pip install "metadatarr[identify]"``) — importing this module never fails,
but calling :func:`identify_audio` without it installed raises
:class:`AudioIdentifyError` with a clear message instead of an ``ImportError``
traceback.

Future tie-in (not implemented here): :mod:`metadatarr.library`'s tagger
could fall back to :func:`identify_audio` for music files whose filename/tags
give it nothing useful to search on.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals

from metadatarr.resolve.base import ResolveResult, enrich as run_enrich, resolve as run_resolve


class AudioIdentifyError(Exception):
    """Raised when audio identification cannot be performed or fails.

    Covers both "the optional ``xazam``/``shazamio_core`` dependency isn't
    installed" and "Shazam returned no match" — callers can check
    :attr:`no_match` to tell the two apart.
    """

    def __init__(self, message: str, *, no_match: bool = False):
        super().__init__(message)
        self.no_match = no_match


@dataclass
class AudioMatch:
    """Result of :func:`identify_audio`: the raw Shazam hit plus enrichment."""

    matched: bool
    title: str = ""
    artist: str = ""
    album: str = ""
    isrc: Optional[str] = None
    shazam_key: str = ""
    cover_art: str = ""
    signals: Optional[Signals] = None
    external_ids: ExternalIds = None  # type: ignore[assignment]
    resolved: Optional[ResolveResult] = None

    def __post_init__(self):
        if self.external_ids is None:
            self.external_ids = ExternalIds()


def _require_xazam():
    try:
        from xazam import ShazamClient, ShazamTransport
    except ImportError as e:
        raise AudioIdentifyError(
            "audio identification requires the optional `xazam` client — "
            "install with `pip install \"metadatarr[identify]\"`"
        ) from e
    return ShazamClient, ShazamTransport


async def _recognize(audio: bytes):
    ShazamClient, ShazamTransport = _require_xazam()
    async with ShazamTransport() as transport:
        client = ShazamClient(transport)
        return await client.identify(audio)


def _extract_isrc(track) -> Optional[str]:
    """Shazam's SONG metadata table sometimes carries an ISRC row."""
    table = track.metadata_table
    for key in ("ISRC", "Isrc"):
        if table.get(key):
            return table[key]
    return None


def _load_audio(source: Union[str, Path, bytes]) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    return Path(source).read_bytes()


def _build_match(result) -> AudioMatch:
    if result is None or not result.matched:
        return AudioMatch(matched=False)

    track = result.track
    isrc = _extract_isrc(track)

    extra = {"shazam_key": track.key, "shazam_url": track.url}
    if track.apple_music_url:
        extra["apple_music_url"] = track.apple_music_url
    if track.spotify_uri:
        extra["spotify_uri"] = track.spotify_uri
    if track.deezer_uri:
        extra["deezer_uri"] = track.deezer_uri
    if isrc:
        extra["isrc"] = isrc

    external_ids = ExternalIds(extra=extra)
    signals = Signals(title=track.title, artist=track.subtitle, medium=MediaType.MUSIC)

    return AudioMatch(
        matched=True,
        title=track.title,
        artist=track.subtitle,
        album=track.metadata_table.get("Album", ""),
        isrc=isrc,
        shazam_key=track.key,
        cover_art=track.cover_art,
        signals=signals,
        external_ids=external_ids,
    )


async def identify_audio_async(
    source: Union[str, Path, bytes],
    *,
    enrich: bool = True,
    resolve: bool = True,
) -> AudioMatch:
    """Async core of :func:`identify_audio`.

    Use this directly from code that already runs inside an event loop
    (e.g. a FastAPI ``async def`` handler) — calling :func:`identify_audio`
    there would fail with "asyncio.run() cannot be called from a running
    event loop". See :func:`identify_audio` for the full contract.
    """
    audio_bytes = _load_audio(source)

    try:
        result = await _recognize(audio_bytes)
    except AudioIdentifyError:
        raise
    except Exception as e:  # pragma: no cover - network/transport failures
        raise AudioIdentifyError(f"audio identification failed: {e}") from e

    match = _build_match(result)
    if not match.matched:
        return match

    if resolve and match.signals is not None:
        match.resolved = run_resolve(match.signals)
        if match.resolved.external_ids:
            match.external_ids = match.external_ids.merge(match.resolved.external_ids)

    if enrich:
        enriched = run_enrich(match.external_ids, medium=MediaType.MUSIC)
        match.external_ids = match.external_ids.merge(enriched)

    return match


def identify_audio(
    source: Union[str, Path, bytes],
    *,
    enrich: bool = True,
    resolve: bool = True,
) -> AudioMatch:
    """Identify a track from an audio file/bytes, then resolve/enrich it.

    ``source`` may be a filesystem path or raw audio bytes. Returns an
    :class:`AudioMatch` with the raw Shazam hit (title/artist/album/isrc/
    ``external_ids``) plus, when a match was found, the cross-catalog
    :class:`~metadatarr.resolve.base.ResolveResult` from
    :func:`metadatarr.resolve.base.resolve` (title+artist search across
    active providers) and — when the Shazam hit carried any ids the
    resolvers recognize — id-derived enrichment merged into
    ``external_ids``.

    Raises :class:`AudioIdentifyError` if ``xazam``/``shazamio_core`` is not
    installed, or if the transport itself fails. A clean Shazam "no match"
    is not an error: it comes back as ``AudioMatch(matched=False)``.

    Sync wrapper around :func:`identify_audio_async` (via ``asyncio.run``) —
    do not call this from inside an already-running event loop; call
    :func:`identify_audio_async` instead.
    """
    return asyncio.run(identify_audio_async(source, enrich=enrich, resolve=resolve))
