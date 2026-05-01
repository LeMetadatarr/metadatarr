"""Entity layer — first-class people, albums, labels, channels.

Each :class:`EntityRecord` is a peer to whatever "work" record a consumer
maintains: it gives a stable id for an artist / actor / director / album /
channel / label, anchored to authoritative external ids (MusicBrainz mbid,
TMDB person id, Wikidata Q-id, …).

Consumers maintain a "work" record (canonical record, in media_archivist
parlance) with a ``relations`` mapping ``{role: [entity_id, ...]}`` so they
can ask "every work whose director is `e_abc`" without scanning freeform
strings.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from metadatarr.resolve.external_ids import ExternalIds


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EntityKind(str, Enum):
    ARTIST = "artist"
    ALBUM = "album"
    RELEASE = "release"
    TRACK = "track"
    LABEL = "label"
    CHANNEL = "channel"
    ACTOR = "actor"
    DIRECTOR = "director"
    PRODUCER = "producer"
    COMPOSER = "composer"
    WRITER = "writer"
    NARRATOR = "narrator"
    HOST = "host"
    AUTHOR = "author"
    OTHER = "other"


# Role on a work's relations dict — same vocabulary as EntityKind, kept as
# a separate name so a relation can refer to entities of a different kind
# in unusual cases.
Role = EntityKind


def _normalize_name(name: str) -> str:
    name = (name or "").lower()
    name = re.sub(r"[\W_]+", " ", name, flags=re.UNICODE)
    return " ".join(name.split())


def _dominant_external_id(ext: ExternalIds, kind: EntityKind) -> Optional[str]:
    """Return the most stable external id we know for ``kind``."""
    if kind == EntityKind.ARTIST:
        # Note: a regular YouTube channel id is *not* an artist id — it
        # identifies an uploader, not a music entity. Only YT Music's
        # artist browseId qualifies, and even then it's last-resort
        # because MBIDs and Metal Archives ids are stronger anchors.
        return (ext.musicbrainz_artist
                or (str(ext.metal_archives_band) if ext.metal_archives_band else None)
                or ext.wikidata
                or ext.extra.get("tmdb_person")
                or ext.extra.get("imdb_person")
                or ext.extra.get("bandcamp_band_id")
                or ext.extra.get("soundcloud_user_id")
                or ext.extra.get("audiodb_artist_id")
                or ext.extra.get("youtube_music_artist_browse_id"))
    if kind == EntityKind.TRACK:
        return (ext.musicbrainz_recording
                or (str(ext.metal_archives_song) if ext.metal_archives_song else None)
                or ext.extra.get("bandcamp_track_id")
                or ext.extra.get("soundcloud_track_id")
                or ext.extra.get("youtube_music_video_id")
                or ext.extra.get("youtube_video_id")
                or ext.extra.get("audiodb_track_id"))
    if kind == EntityKind.RELEASE:
        return (ext.musicbrainz_release
                or (str(ext.fanedit_id) if ext.fanedit_id else None))
    if kind == EntityKind.ALBUM:
        return (ext.musicbrainz_release_group
                or ext.musicbrainz_release
                or (str(ext.metal_archives_release) if ext.metal_archives_release else None)
                or ext.extra.get("bandcamp_album_id")
                or ext.extra.get("audiodb_album_id")
                or ext.extra.get("youtube_music_album_browse_id"))
    if kind in {EntityKind.ACTOR, EntityKind.DIRECTOR, EntityKind.PRODUCER,
                EntityKind.COMPOSER, EntityKind.WRITER, EntityKind.NARRATOR,
                EntityKind.HOST}:
        return ((str(ext.tmdb_person) if ext.tmdb_person else None)
                or ext.imdb_person
                or (str(ext.metal_archives_artist) if ext.metal_archives_artist else None)
                or ext.wikidata
                or ext.extra.get("tmdb_person")
                or ext.extra.get("imdb_person"))
    if kind == EntityKind.AUTHOR:
        return (ext.olid or ext.goodreads or ext.extra.get("goodreads_author")
                or ext.wikidata)
    if kind == EntityKind.LABEL:
        return ((str(ext.metal_archives_label) if ext.metal_archives_label else None)
                or ext.extra.get("musicbrainz_label") or ext.wikidata)
    if kind == EntityKind.CHANNEL:
        return ext.extra.get("youtube_channel_id")
    return None


def allocate_entity_id(kind: EntityKind, *, name: str = "",
                       external_ids: Optional[ExternalIds] = None,
                       role: Optional["Role"] = None) -> str:
    """Deterministic entity id from external ids (preferred) or normalized name.

    When *external_ids* identify the entity unambiguously, role is ignored —
    the same authoritative ID always points to the same person/group, even
    if they wear different hats on different works. When we fall back to the
    name-based seed, *role* is mixed in: two unrelated "John Smith" entries
    appearing in DIRECTOR vs WRITER roles must not collapse to the same
    entity.
    """
    ext = external_ids or ExternalIds()
    dom = _dominant_external_id(ext, kind)
    if dom:
        seed = f"{kind.value}|ext:{dom}"
    else:
        role_value = role.value if role is not None else kind.value
        seed = f"{kind.value}|role:{role_value}|name:{_normalize_name(name)}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


class ProviderEntity(BaseModel):
    """One entity contribution from a single provider response."""

    model_config = ConfigDict(extra="forbid")

    kind: EntityKind
    name: str
    role: Optional[Role] = None
    external_ids: ExternalIds = Field(default_factory=ExternalIds)


class EntityRecord(BaseModel):
    """One entry per *entity* in an entities sidecar."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: EntityKind
    name: str
    aliases: List[str] = Field(default_factory=list)
    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    members: List[str] = Field(default_factory=list)  # sub-entity ids
    works: List[str] = Field(default_factory=list)    # work ids this entity participates in
    first_seen: str = Field(default_factory=_utcnow)
    last_updated: str = Field(default_factory=_utcnow)

    def touch(self) -> None:
        self.last_updated = _utcnow()

    def merge_alias(self, name: str) -> None:
        if not name or name == self.name:
            return
        if name in self.aliases:
            return
        self.aliases.append(name)


class EntitySidecar(BaseModel):
    """Top-level shape of an entities sidecar."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    entities: Dict[str, EntityRecord] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mutation helpers — stateless, operate on a sidecar instance
# ---------------------------------------------------------------------------

def upsert_entity(sidecar: EntitySidecar, candidate: ProviderEntity, *,
                  role_hint: Optional[Role] = None) -> str:
    """Insert or update a :class:`ProviderEntity`; return its ``entity_id``.

    Conservative merge:

    - If we have any external id for the candidate, the entity_id is derived
      from it; matching records absorb new aliases/external_ids.
    - Else the entity_id is derived from the normalized name. Same name across
      providers collapses to one entity; the resulting record's
      ``external_ids`` accumulate.
    """
    kind = candidate.kind
    eid = allocate_entity_id(kind, name=candidate.name,
                             external_ids=candidate.external_ids,
                             role=candidate.role or role_hint)
    rec = sidecar.entities.get(eid)
    if rec is None:
        rec = EntityRecord(
            id=eid,
            kind=kind,
            name=candidate.name,
            external_ids=candidate.external_ids,
        )
        sidecar.entities[eid] = rec
    else:
        rec.merge_alias(candidate.name)
        rec.external_ids = rec.external_ids.merge(candidate.external_ids)
        rec.touch()
    return eid


def attach_work(sidecar: EntitySidecar, entity_id: str, work_id: str) -> None:
    rec = sidecar.entities.get(entity_id)
    if rec is None:
        return
    if work_id and work_id not in rec.works:
        rec.works.append(work_id)
        rec.touch()


def entities_by_kind(sidecar: EntitySidecar, kind: EntityKind) -> List[EntityRecord]:
    return [r for r in sidecar.entities.values() if r.kind == kind]
