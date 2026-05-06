"""Bandcamp metadata provider via :mod:`py_bandcamp` (optional dep).

Bandcamp exposes stable numeric IDs from the ``data-tralbum`` JSON blob
embedded in every track and album page:

- ``band_id``  — artist/band (never changes even if the subdomain does)
- ``track_id`` — individual track
- ``album_id`` — album a track belongs to, or the album itself

URL slugs (subdomain + path) are NOT used as canonical ids because Bandcamp
allows artists to rename them.  A URL is stored as plain metadata so the
consumer can link back to the page, but it is not used for entity resolution.

Keys written to :attr:`ExternalIds.extra`:

- ``bandcamp_band_id``  — numeric artist/band id
- ``bandcamp_track_id`` — numeric track id
- ``bandcamp_album_id`` — numeric album id
- ``bandcamp_track_url`` / ``bandcamp_album_url`` / ``bandcamp_artist_url``
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

import requests

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.bandcamp")


def _safe_int_year(value) -> Optional[int]:
    if value is None:
        return None
    text = str(value)
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


# ---------------------------------------------------------------------------
# Slug derivation — Bandcamp URLs follow ``<artist_url>/track/<slug>`` where
# the slug is deterministic-ish: lowercase, ASCII-ish, hyphens for spaces,
# apostrophes/punctuation dropped. We use this to *propose* candidate track
# URLs that a HEAD request can then confirm — useful when an artist mapping
# tells us the Bandcamp page exists but the track itself wasn't indexed by
# py_bandcamp's search.
# ---------------------------------------------------------------------------

_SLUG_DROP = re.compile(r"[^a-z0-9\s_-]+")
_SLUG_WS = re.compile(r"[\s_]+")
_SLUG_DASHES = re.compile(r"-{2,}")


def slugify_title(title: str) -> str:
    """Approximate Bandcamp's track-slug rule. Not perfect — Bandcamp does
    let artists override the slug — but right for the vast majority of
    auto-generated track URLs."""
    s = (title or "").lower()
    s = _SLUG_DROP.sub("", s)
    s = _SLUG_WS.sub("-", s).strip("-")
    s = _SLUG_DASHES.sub("-", s)
    return s


def derive_track_url(artist_url: str, title: str) -> Optional[str]:
    """Build a candidate Bandcamp track URL from an artist URL + a title.

    Returns ``None`` if either input is empty. Does not hit the network —
    callers should HEAD-probe the result to confirm it actually exists.
    """
    if not (artist_url and title):
        return None
    slug = slugify_title(title)
    if not slug:
        return None
    base = artist_url.rstrip("/") + "/"
    return urljoin(base, f"track/{slug}")


def confirm_track_url(url: str, *, timeout: float = 10.0) -> bool:
    """HEAD-probe *url* and return True iff it resolves to a 2xx (or 3xx).

    Used after :func:`derive_track_url` to confirm a candidate before we
    write it into ``ExternalIds.extra``.
    """
    if not url:
        return False
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout)
    except requests.RequestException:
        return False
    return 200 <= resp.status_code < 400


class BandcampProvider(MetadataProvider):
    name = "bandcamp"
    media = {MediaType.MUSIC}

    def __init__(self) -> None:
        try:
            from py_bandcamp import BandCamp  # noqa: WPS433
            self._client = BandCamp()
            self._available = True
        except ImportError:
            self._client = None
            self._available = False
        except Exception as exc:  # pragma: no cover
            LOG.warning("py_bandcamp init failed: %s", exc)
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
            LOG.warning("bandcamp search failed: %s", exc)
            return None

        if not hits:
            return None

        top = hits[0]
        track_url = getattr(top, "url", None)
        title = getattr(top, "title", None)

        artist_obj = getattr(top, "artist", None)
        artist_name = getattr(artist_obj, "name", None) or (
            artist_obj if isinstance(artist_obj, str) else None
        )
        artist_url = getattr(artist_obj, "url", None) if not isinstance(artist_obj, str) else None

        album_obj = getattr(top, "album", None)
        album_title = getattr(album_obj, "title", None)
        album_url = getattr(album_obj, "url", None)

        runtime = getattr(top, "duration", None)
        try:
            runtime = float(runtime) if runtime is not None else None
        except (TypeError, ValueError):
            runtime = None

        band_id = getattr(top, "band_id", None)
        track_id_num = getattr(top, "track_id", None)
        album_id_num = getattr(top, "album_id", None)

        external_extra: dict = {}
        if band_id is not None:
            external_extra["bandcamp_band_id"] = str(band_id)
        if track_id_num is not None:
            external_extra["bandcamp_track_id"] = str(track_id_num)
        if album_id_num is not None:
            external_extra["bandcamp_album_id"] = str(album_id_num)
        if track_url:
            external_extra["bandcamp_track_url"] = str(track_url)
        if album_url:
            external_extra["bandcamp_album_url"] = str(album_url)
        if artist_url:
            external_extra["bandcamp_artist_url"] = str(artist_url)

        relations: dict = {}
        if artist_name:
            artist_extra: dict = {}
            if band_id is not None:
                artist_extra["bandcamp_band_id"] = str(band_id)
            if artist_url:
                artist_extra["bandcamp_artist_url"] = str(artist_url)
            relations[EntityRole.ARTIST] = [ProviderEntity(
        role=EntityRole.ARTIST,
                name=artist_name,
                external_ids=ExternalIds(extra=artist_extra),
            )]
        if album_title:
            album_extra: dict = {}
            if album_id_num is not None:
                album_extra["bandcamp_album_id"] = str(album_id_num)
            if album_url:
                album_extra["bandcamp_album_url"] = str(album_url)
            relations[EntityRole.ALBUM] = [ProviderEntity(
        role=EntityRole.ALBUM,
                name=album_title,
                external_ids=ExternalIds(extra=album_extra),
            )]

        return ProviderMatch(
            provider=self.name,
            confidence=0.6,
            signals=Signals(
                title=title or signals.title,
                artist=artist_name,
                runtime=runtime,
                year=_safe_int_year(getattr(top, "year", None)),
                medium=MediaType.MUSIC,
            ),
            external_ids=ExternalIds(extra=external_extra),
            relations=relations,
        )


    # ------------------------------------------------------------------
    # ID-keyed enrichment — Bandcamp URL → numeric ids via py_bandcamp
    # ------------------------------------------------------------------

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Resolve Bandcamp numeric ids from any Bandcamp URL the caller
        already has.

        Triggers (independently optional):

        - ``extra.bandcamp_track_url`` → ``bandcamp_track_id``
          (+ ``bandcamp_band_id`` and ``bandcamp_album_id`` when py_bandcamp
          surfaces them on the track page)
        - ``extra.bandcamp_album_url`` → ``bandcamp_album_id``
          (+ ``bandcamp_band_id``)

        Artist-only URLs are not resolved here — :class:`BandcampArtist`
        does not yet expose a numeric ``band_id`` on the artist landing
        page. Get the band id by enriching a track or album URL the artist
        owns instead.
        """
        if not self._available:
            return None

        urls = external_ids.extra
        artist_url = urls.get("bandcamp_artist_url")
        track_url = urls.get("bandcamp_track_url")
        album_url = urls.get("bandcamp_album_url")
        if not (artist_url or track_url or album_url):
            return None

        out_extra: dict = {}

        if artist_url and "bandcamp_band_id" not in urls:
            # Available in py_bandcamp ≥0.10 (BandcampArtist.band_id pulls
            # the numeric id from /releases). Earlier versions raise
            # AttributeError which we swallow.
            try:
                from py_bandcamp import BandcampArtist  # noqa: WPS433
                a = BandcampArtist.from_url(artist_url)
                band_id = getattr(a, "band_id", None)
            except Exception as exc:
                LOG.debug("bandcamp artist from_url failed: %s", exc)
                band_id = None
            if band_id:
                out_extra["bandcamp_band_id"] = str(band_id)

        if track_url:
            try:
                from py_bandcamp import BandcampTrack  # noqa: WPS433
                t = BandcampTrack.from_url(track_url)
            except Exception as exc:
                LOG.warning("bandcamp track from_url failed: %s", exc)
                t = None
            if t is not None:
                if t.track_id and "bandcamp_track_id" not in urls:
                    out_extra["bandcamp_track_id"] = str(t.track_id)
                if t.band_id and "bandcamp_band_id" not in urls:
                    out_extra["bandcamp_band_id"] = str(t.band_id)
                if t.album_id and "bandcamp_album_id" not in urls:
                    out_extra["bandcamp_album_id"] = str(t.album_id)

        if album_url:
            try:
                from py_bandcamp import BandcampAlbum  # noqa: WPS433
                a = BandcampAlbum.from_url(album_url)
            except Exception as exc:
                LOG.warning("bandcamp album from_url failed: %s", exc)
                a = None
            if a is not None:
                if a.album_id and "bandcamp_album_id" not in urls \
                   and "bandcamp_album_id" not in out_extra:
                    out_extra["bandcamp_album_id"] = str(a.album_id)
                if a.band_id and "bandcamp_band_id" not in urls \
                   and "bandcamp_band_id" not in out_extra:
                    out_extra["bandcamp_band_id"] = str(a.band_id)

        if not out_extra:
            return None
        return ExternalIds(extra=out_extra)


register(BandcampProvider())
