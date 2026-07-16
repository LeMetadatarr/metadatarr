"""MusicBrainz provider — free, no API key, but rate-limited (1 req/s)."""
from __future__ import annotations

import logging
from typing import List, Optional

import requests

from metadatarr.version import __version__
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.transport import make_session
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType, PlaybackType
from mediavocab.models.signals import Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.musicbrainz")
_BASE = "https://musicbrainz.org/ws/2"
_UA = f"metadatarr/{__version__} (+https://github.com/TigreGotico/metadatarr)"
_SESSION = make_session()


class MusicBrainzProvider(MetadataProvider):
    name = "musicbrainz"
    media = {MediaType.MUSIC}
    playback_type = {PlaybackType.AUDIO}

    def is_available(self) -> bool:
        return True

    def _search(self, signals: Signals) -> List[dict]:
        if not (signals.title and signals.artist):
            return []
        if signals.medium and signals.medium != MediaType.MUSIC:
            return []
        params = {
            "query": f'recording:"{signals.title}" AND artist:"{signals.artist}"',
            "fmt": "json",
            "limit": 5,
        }
        try:
            resp = _SESSION.get(f"{_BASE}/recording", params=params,
                                headers={"User-Agent": _UA}, timeout=20)
            resp.raise_for_status()
            return resp.json().get("recordings") or []
        except requests.RequestException as e:
            LOG.warning("MusicBrainz lookup failed: %s", e)
            return []

    def _build_match(self, rec: dict, signals: Signals) -> ProviderMatch:
        confidence = float(rec.get("score", 0)) / 100.0

        artist_credit = rec.get("artist-credit") or []
        artist_name = artist_credit[0].get("name") if artist_credit else None
        artist_mbid = (artist_credit[0].get("artist") or {}).get("id") if artist_credit else None

        release = (rec.get("releases") or [{}])[0]
        country = release.get("country")
        date = release.get("date") or rec.get("first-release-date")
        year = int(date[:4]) if date and len(date) >= 4 and date[:4].isdigit() else None

        runtime_ms = rec.get("length")
        runtime_s = float(runtime_ms) / 1000 if isinstance(runtime_ms, (int, float)) else None

        artists: list[ProviderEntity] = []
        for credit in artist_credit:
            artist_obj = credit.get("artist") or {}
            cand_name = (credit.get("name")
                         or artist_obj.get("name")
                         or artist_obj.get("sort-name"))
            if not cand_name:
                continue
            artists.append(ProviderEntity(
        role=EntityRole.ARTIST,
                name=cand_name,
                external_ids=ExternalIds(
                    musicbrainz_artist=artist_obj.get("id"),
                ),
            ))
        relations: dict = {}
        if artists:
            relations[EntityRole.ARTIST] = artists

        cand = Signals(
            title=rec.get("title"),
            artist=artist_name,
            year=year,
            country=country,
            runtime=runtime_s,
            medium=MediaType.MUSIC,
        )
        return ProviderMatch(
            provider=self.name,
            confidence=confidence * match_quality(signals, cand),
            signals=cand,
            external_ids=ExternalIds(
                musicbrainz_recording=rec.get("id"),
                musicbrainz_release=release.get("id") or None,
                musicbrainz_artist=artist_mbid,
            ),
            relations=relations,
        )

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        recordings = self._search(signals)
        if not recordings:
            return None
        return self._build_match(recordings[0], signals)

    def lookup_candidates(self, signals: Signals) -> List[ProviderMatch]:
        """Up to 5 ranked recordings — same single search call as :meth:`lookup`."""
        recordings = self._search(signals)
        out = [self._build_match(r, signals) for r in recordings]
        out.sort(key=lambda m: m.confidence, reverse=True)
        return out


    # ------------------------------------------------------------------
    # ID-keyed enrichment — MBID → URL relations (Wikidata, Bandcamp,
    # SoundCloud, Discogs, Allmusic, IMDb, official site, etc.)
    # ------------------------------------------------------------------

    # MusicBrainz `relation type` strings we know how to map onto
    # ExternalIds. Each entry maps a (entity-type, relation-type) pair to
    # a callable that takes the relation dict and returns
    # ``(field_name, value)`` for first-class fields, or
    # ``("extra:<key>", value)`` for the extras dict.
    _URL_REL_FIRST_CLASS = {
        "wikidata":  lambda url: ("wikidata", url.rsplit("/", 1)[-1]),
        "discogs":   lambda url: ("extra:discogs_url", url),
        "allmusic":  lambda url: ("extra:allmusic_url", url),
        "imdb":      lambda url: ("imdb",
                                  url.rstrip("/").rsplit("/", 1)[-1]),
    }
    # url-relation `type` field → key in extra (URL preserved as-is).
    _URL_REL_EXTRA = {
        "bandcamp":          "bandcamp_artist_url",
        "soundcloud":        "soundcloud_artist_url",
        "youtube":           "youtube_channel_url",
        "youtube music":     "youtube_music_artist_url",
        "official homepage": "official_site",
    }

    def _fetch_mb_entity(self, kind: str, mbid: str,
                         inc: str = "url-rels") -> Optional[dict]:
        """Tiny wrapper around the MusicBrainz `/{kind}/{mbid}?inc=...`
        endpoint. Returns ``None`` on any error so callers can fall through
        to other enrichment paths."""
        try:
            resp = _SESSION.get(
                f"{_BASE}/{kind}/{mbid}",
                params={"inc": inc, "fmt": "json"},
                headers={"User-Agent": _UA}, timeout=20,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            LOG.warning("MusicBrainz %s fetch failed: %s", kind, e)
            return None

    @classmethod
    def _absorb_url_relations(cls, payload: dict, out: ExternalIds) -> None:
        """Walk a MusicBrainz JSON payload's ``relations[]`` array and
        write any URL relations we recognise into *out*."""
        for rel in (payload.get("relations") or []):
            if rel.get("target-type") != "url":
                continue
            rel_type = (rel.get("type") or "").lower()
            url = ((rel.get("url") or {}).get("resource") or "").strip()
            if not url:
                continue
            if rel_type in cls._URL_REL_FIRST_CLASS:
                field, value = cls._URL_REL_FIRST_CLASS[rel_type](url)
                if field.startswith("extra:"):
                    out.extra.setdefault(field[6:], value)
                elif getattr(out, field, None) in (None, ""):
                    setattr(out, field, value)
            elif rel_type in cls._URL_REL_EXTRA:
                out.extra.setdefault(cls._URL_REL_EXTRA[rel_type], url)

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Resolve MusicBrainz URL relations for any MBID the caller has.

        MusicBrainz is *the* gateway for music cross-references — most
        artists list their Wikidata Q-id, Discogs, Bandcamp, SoundCloud,
        official site, and Allmusic links inside the artist's url-relations
        block. Same for releases (label sites) and recordings (YouTube
        videos), but we only touch artist/release/release-group/recording
        — the four MBID slots :class:`ExternalIds` carries.
        """
        out = ExternalIds()
        out.extra = {}

        keys = (
            ("artist",        external_ids.musicbrainz_artist),
            ("release",       external_ids.musicbrainz_release),
            ("release-group", external_ids.musicbrainz_release_group),
            ("recording",     external_ids.musicbrainz_recording),
        )
        any_call = False
        for kind, mbid in keys:
            if not mbid:
                continue
            any_call = True
            payload = self._fetch_mb_entity(kind, mbid)
            if payload is None:
                continue
            self._absorb_url_relations(payload, out)

        if not any_call or out.is_empty():
            return None
        return out


    def list_variants(self, external_ids: ExternalIds,
                      signals=None) -> List[ProviderEntity]:
        """Expand a MusicBrainz release-group → its individual releases."""
        mbrgid = external_ids.musicbrainz_release_group
        if not mbrgid:
            return []
        try:
            resp = _SESSION.get(
                f"{_BASE}/release",
                params={"release-group": mbrgid, "fmt": "json", "limit": 100},
                headers={"User-Agent": _UA}, timeout=20,
            )
            resp.raise_for_status()
            releases = resp.json().get("releases") or []
        except requests.RequestException as e:
            LOG.warning("MusicBrainz release-group expand failed: %s", e)
            return []
        out = []
        for rel in releases:
            mbid = rel.get("id")
            if not mbid:
                continue
            out.append(ProviderEntity(
                role=EntityRole.OTHER,
                name=rel.get("title") or mbid,
                external_ids=ExternalIds(musicbrainz_release=mbid),
            ))
        return out


register(MusicBrainzProvider())
