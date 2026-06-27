"""SoundCloud metadata provider via :mod:`nuvem_de_som` (optional dep).

SoundCloud exposes stable numeric IDs for every resource:

- ``track_id`` — unique track id (never changes even if the slug does)
- ``user_id``  — unique user/artist id

URL slugs (``/<user>/<track-slug>``) are NOT used as canonical ids; they can
change when an artist renames their profile or a track slug is updated.  The
URL is stored as plain metadata so the consumer can link back to the page.

Keys written to :attr:`ExternalIds.extra`:

- ``soundcloud_track_id``  — numeric track id
- ``soundcloud_user_id``   — numeric user/artist id
- ``soundcloud_track_url`` / ``soundcloud_artist_url``
"""
from __future__ import annotations

import logging
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType, PlaybackType
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.soundcloud")


def _attr(obj, *names):
    """Pull the first non-None attribute / dict-key from ``obj``."""
    for name in names:
        if obj is None:
            return None
        if isinstance(obj, dict):
            v = obj.get(name)
        else:
            v = getattr(obj, name, None)
        if v not in (None, ""):
            return v
    return None


class SoundCloudProvider(MetadataProvider):
    name = "soundcloud"
    media = {MediaType.MUSIC}
    playback_type = {PlaybackType.AUDIO}

    def __init__(self) -> None:
        try:
            from nuvem_de_som import SoundCloud  # noqa: WPS433
            self._client = SoundCloud()
            self._available = True
        except ImportError:
            self._client = None
            self._available = False
        except Exception as exc:  # pragma: no cover
            LOG.warning("nuvem_de_som init failed: %s", exc)
            self._client = None
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not (self._available and signals.title):
            return None
        if signals.medium and signals.medium != MediaType.MUSIC:
            return None

        query = f"{signals.artist} {signals.title}" if signals.artist else signals.title
        try:
            hits = list(self._client.search_tracks(query))
        except Exception as exc:
            LOG.warning("soundcloud search failed: %s", exc)
            return None

        if not hits:
            return None
        top = hits[0]

        title = _attr(top, "title", "name")
        track_url = _attr(top, "url", "permalink_url", "watch_url")
        artist_name = _attr(top, "artist", "uploader", "user")
        # nuvem_de_som returns a flat dict where the artist URL sits in
        # ``artist_url`` alongside the string ``artist`` name; older shapes
        # stored both inside a nested user/uploader object. Cover both.
        artist_url = _attr(top, "artist_url", "uploader_url", "user_url")
        if artist_url is None and not isinstance(artist_name, str):
            artist_url = _attr(artist_name, "url", "permalink_url")
            artist_name = _attr(artist_name, "username", "name")

        # SoundCloud creators often title tracks as "<artist> - <title>"
        # (no separate album field); strip the redundant prefix so the
        # resolver's title comparison doesn't drop the match for what is
        # really an artist-prefix formatting difference. Tolerate any
        # punctuation/whitespace separator (` - `, `  `, `: `, em/en dash).
        if title and isinstance(artist_name, str) and artist_name:
            lowered = title.lower()
            artist_l = artist_name.lower()
            if lowered.startswith(artist_l):
                rest = title[len(artist_name):].lstrip(" -–—:·|/")
                if rest:
                    title = rest

        runtime_ms = _attr(top, "duration_ms", "duration")
        try:
            runtime = float(runtime_ms) / 1000.0 if isinstance(runtime_ms, (int, float)) and runtime_ms > 1000 else (
                float(runtime_ms) if isinstance(runtime_ms, (int, float)) else None
            )
        except (TypeError, ValueError):
            runtime = None

        track_id_num = _attr(top, "track_id")
        user_id_num = _attr(top, "user_id")

        extra: dict = {}
        if track_id_num is not None:
            extra["soundcloud_track_id"] = str(track_id_num)
        if user_id_num is not None:
            extra["soundcloud_user_id"] = str(user_id_num)
        if track_url:
            extra["soundcloud_track_url"] = str(track_url)
        if artist_url:
            extra["soundcloud_artist_url"] = str(artist_url)

        relations: dict = {}
        if artist_name:
            artist_extra: dict = {}
            if user_id_num is not None:
                artist_extra["soundcloud_user_id"] = str(user_id_num)
            if artist_url:
                artist_extra["soundcloud_artist_url"] = str(artist_url)
            relations[EntityRole.ARTIST] = [ProviderEntity(
        role=EntityRole.ARTIST,
                name=str(artist_name),
                external_ids=ExternalIds(extra=artist_extra),
            )]

        return ProviderMatch(
            provider=self.name,
            confidence=0.55,
            signals=Signals(
                title=title or signals.title,
                artist=str(artist_name) if artist_name else None,
                runtime=runtime,
                medium=MediaType.MUSIC,
            ),
            external_ids=ExternalIds(extra=extra),
            relations=relations,
        )


    # ------------------------------------------------------------------
    # ID-keyed enrichment — SoundCloud URL → numeric ids via upstream
    # `resolve_user` / `resolve_track` (nuvem_de_som).
    # ------------------------------------------------------------------

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Resolve SoundCloud numeric ids from any SoundCloud URL.

        Triggers (independently optional):

        - ``extra.soundcloud_artist_url`` → ``soundcloud_user_id``
          (via :meth:`SoundCloudBase.resolve_user`)
        - ``extra.soundcloud_track_url``  → ``soundcloud_track_id``
          (+ ``soundcloud_user_id`` when the upstream surfaces the
          uploader id, via :meth:`SoundCloudBase.resolve_track`)
        """
        if not self._available:
            return None

        urls = external_ids.extra
        artist_url = urls.get("soundcloud_artist_url")
        track_url = urls.get("soundcloud_track_url")
        if not (artist_url or track_url):
            return None

        out_extra: dict = {}

        if artist_url and "soundcloud_user_id" not in urls:
            try:
                user = self._client.resolve_user(artist_url)
            except Exception as exc:
                LOG.debug("soundcloud resolve_user failed: %s", exc)
                user = None
            if user is not None and user.get("user_id") is not None:
                out_extra["soundcloud_user_id"] = str(user["user_id"])

        if track_url:
            track = None
            # `resolve_track` was added in nuvem_de_som ≥0.3 — fall back
            # silently when the installed version is older.
            try:
                track = self._client.resolve_track(track_url)
            except AttributeError:
                track = None
            except Exception as exc:
                LOG.debug("soundcloud resolve_track failed: %s", exc)
                track = None
            if track is not None:
                if track.get("track_id") is not None \
                   and "soundcloud_track_id" not in urls:
                    out_extra["soundcloud_track_id"] = str(track["track_id"])
                if track.get("user_id") is not None \
                   and "soundcloud_user_id" not in urls \
                   and "soundcloud_user_id" not in out_extra:
                    out_extra["soundcloud_user_id"] = str(track["user_id"])

        if not out_extra:
            return None
        return ExternalIds(extra=out_extra)


register(SoundCloudProvider())
