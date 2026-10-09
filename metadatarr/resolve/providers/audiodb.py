"""TheAudioDB metadata provider (free key — no auth required).

TheAudioDB is a community music database with stable numeric IDs for
artists, albums, and tracks, plus MusicBrainz cross-references and
music-video metadata (director, YouTube URL, view counts).

Free API key ``123`` is documented at theaudiodb.com/api_guide.php.

Keys written to :attr:`ExternalIds.extra`:

- ``audiodb_artist_id``  — stable numeric artist id
- ``audiodb_album_id``   — stable numeric album id
- ``audiodb_track_id``   — stable numeric track id
- ``music_video_url``    — YouTube URL of the official music video (when present)
- ``music_video_director``
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType, PlaybackType
from mediavocab.models.signals import Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.audiodb")


class AudioDBProvider(MetadataProvider):
    name = "audiodb"
    media = {MediaType.MUSIC}
    playback_type = {PlaybackType.AUDIO}

    def __init__(self) -> None:
        from pyaudiodb import AudioDBClient
        self._client = AudioDBClient()

    def is_available(self) -> bool:
        return True  # no auth, no optional deps

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium and signals.medium != MediaType.MUSIC:
            return None

        artist_query = signals.artist or ""
        try:
            tracks = self._client.search_track(artist_query, signals.title)
        except requests.RequestException as exc:
            LOG.warning("audiodb search_track failed query=%r artist=%r: %s",
                        signals.title, artist_query, exc)
            return None
        except Exception:
            LOG.exception("audiodb search_track unexpected error query=%r artist=%r",
                          signals.title, artist_query)
            return None

        if not tracks:
            return None
        top = tracks[0]

        extra: dict = {}
        extra["audiodb_track_id"] = top.id
        if top.album_id:
            extra["audiodb_album_id"] = top.album_id
        if top.artist_id:
            extra["audiodb_artist_id"] = top.artist_id
        if top.musicbrainz_id:
            pass  # surfaces via first-class field below
        if top.music_vid_url:
            extra["music_video_url"] = top.music_vid_url
        if top.music_vid_director:
            extra["music_video_director"] = top.music_vid_director

        relations: dict = {}
        if top.artist:
            artist_extra: dict = {}
            if top.artist_id:
                artist_extra["audiodb_artist_id"] = top.artist_id
            # musicbrainz_artist is already in the first-class ExternalIds field below
            relations[EntityRole.ARTIST] = [ProviderEntity(
        role=EntityRole.ARTIST,
                name=top.artist,
                external_ids=ExternalIds(
                    musicbrainz_artist=top.musicbrainz_artist_id,
                    extra=artist_extra,
                ),
            )]
        cand_signals = Signals(
            title=top.title,
            artist=top.artist,
            runtime=top.duration_seconds,
            medium=MediaType.MUSIC,
        )
        return ProviderMatch(
            provider=self.name,
            confidence=0.65 * match_quality(signals, cand_signals),
            signals=cand_signals,
            external_ids=ExternalIds(
                musicbrainz_recording=top.musicbrainz_id,
                extra=extra,
            ),
            relations=relations,
        )


    # ------------------------------------------------------------------
    # ID-keyed enrichment — uses MusicBrainz IDs as the lookup key
    # ------------------------------------------------------------------

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Resolve AudioDB-side records keyed by MusicBrainz IDs.

        Triggers, in priority order:

        - ``musicbrainz_artist`` → ``get_artist_by_mbid`` → emits
          ``audiodb_artist_id``.
        - ``musicbrainz_release`` → ``get_album_by_mbid`` → emits
          ``audiodb_album_id`` (and the album's MB release group / Wikidata
          when AudioDB happens to know them).
        - ``musicbrainz_recording`` → ``get_track_by_mbid`` → emits
          ``audiodb_track_id`` plus the track's musicbrainz_album/artist
          when AudioDB has joined them upstream.
        """
        out_extra: dict = {}
        out = ExternalIds()

        mbid_artist = external_ids.musicbrainz_artist
        if mbid_artist:
            try:
                artist = self._client.get_artist_by_mbid(mbid_artist)
            except requests.RequestException as exc:
                LOG.warning("audiodb get_artist_by_mbid failed mbid=%r: %s", mbid_artist, exc)
                artist = None
            except Exception:
                LOG.exception("audiodb get_artist_by_mbid unexpected error mbid=%r", mbid_artist)
                artist = None
            if artist is not None and getattr(artist, "id", None):
                out_extra["audiodb_artist_id"] = str(artist.id)

        mbid_release = external_ids.musicbrainz_release
        if mbid_release:
            try:
                album = self._client.get_album_by_mbid(mbid_release)
            except requests.RequestException as exc:
                LOG.warning("audiodb get_album_by_mbid failed mbid=%r: %s", mbid_release, exc)
                album = None
            except Exception:
                LOG.exception("audiodb get_album_by_mbid unexpected error mbid=%r", mbid_release)
                album = None
            if album is not None and getattr(album, "id", None):
                out_extra["audiodb_album_id"] = str(album.id)
                # AudioDB sometimes fills release-group MBID even when the
                # caller only had the release MBID — preserve it.
                rg = getattr(album, "musicbrainz_id", None)
                if rg and not out.musicbrainz_release_group:
                    out.musicbrainz_release_group = rg
                wd = getattr(album, "wikidata_id", None)
                if wd and not out.wikidata:
                    out.wikidata = wd

        mbid_recording = external_ids.musicbrainz_recording
        if mbid_recording:
            try:
                track = self._client.get_track_by_mbid(mbid_recording)
            except requests.RequestException as exc:
                LOG.warning("audiodb get_track_by_mbid failed mbid=%r: %s", mbid_recording, exc)
                track = None
            except Exception:
                LOG.exception("audiodb get_track_by_mbid unexpected error mbid=%r", mbid_recording)
                track = None
            if track is not None and getattr(track, "id", None):
                out_extra["audiodb_track_id"] = str(track.id)
                album_mbid = getattr(track, "musicbrainz_album_id", None)
                if album_mbid and not out.musicbrainz_release:
                    out.musicbrainz_release = album_mbid
                artist_mbid = getattr(track, "musicbrainz_artist_id", None)
                if artist_mbid and not out.musicbrainz_artist:
                    out.musicbrainz_artist = artist_mbid

        if not out_extra and out == ExternalIds():
            return None
        out.extra = out_extra
        return out


register(AudioDBProvider())
