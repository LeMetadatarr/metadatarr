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

from mediavocab.models import ExternalIds


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EntityKind(str, Enum):
    """Resolver-internal *role/kind* taxonomy used to key the
    :attr:`ProviderMatch.relations` dictionary.

    This enum deliberately mixes structural kinds (``ARTIST``, ``LABEL``,
    ``STUDIO``, ``CHANNEL``, ``CHARACTER``) with relational roles
    (``ACTOR``, ``DIRECTOR``, ``COMPOSER``, …) and Work-level
    sub-types (``ALBUM``, ``RELEASE``, ``TRACK``). Providers report
    "this entity is the director of the work" by emitting
    ``ProviderEntity(kind=EntityKind.DIRECTOR, ...)`` — the kind *is* the
    role in this layer, which is convenient for the dispatcher and for
    keying ``relations[role]``.

    Callers building canonical :class:`mediavocab.Entity` /
    :class:`mediavocab.Credit` records should round-trip through
    :meth:`to_mediavocab_kind` (structural ``EntityKind`` —
    ``PERSON`` / ``GROUP`` / ``ORGANISATION`` / ``OTHER``) and
    :meth:`to_mediavocab_role` (typed ``RelationRole``). Spec axiom 1
    keeps the foundation enums orthogonal; this enum trades that
    orthogonality for ergonomic provider dispatch.
    """

    ARTIST = "artist"
    ALBUM = "album"
    RELEASE = "release"
    TRACK = "track"
    LABEL = "label"
    CHANNEL = "channel"
    ACTOR = "actor"
    VOICE_ACTOR = "voice_actor"
    DIRECTOR = "director"
    PRODUCER = "producer"
    COMPOSER = "composer"
    WRITER = "writer"
    NARRATOR = "narrator"
    HOST = "host"
    AUTHOR = "author"
    STUDIO = "studio"
    CHARACTER = "character"
    OTHER = "other"

    def to_mediavocab_kind(self):
        """Return the structural ``mediavocab.EntityKind`` for this value.

        ``ALBUM`` / ``RELEASE`` / ``TRACK`` are Works (not Entities) per
        the mediavocab spec; they map to ``EntityKind.OTHER`` here as a
        signal to the caller that the right model is ``Work``, not
        ``Entity``.
        """
        from mediavocab import EntityKind as _MvEntityKind
        return _STRUCTURAL_KIND.get(self, _MvEntityKind.OTHER)

    def to_mediavocab_role(self):
        """Return the typed ``mediavocab.RelationRole`` for this value, or
        ``None`` when this kind is not a contribution role (e.g. ``ALBUM``,
        ``ARTIST``, ``CHARACTER``)."""
        return _RELATION_ROLE.get(self)


# Lazy maps populated below to avoid an import cycle with mediavocab.
_STRUCTURAL_KIND: dict = {}
_RELATION_ROLE: dict = {}


def _build_bridges():
    from mediavocab import EntityKind as _MvEntityKind
    from mediavocab import RelationRole as _MvRelationRole
    _STRUCTURAL_KIND.update({
        EntityKind.ARTIST:      _MvEntityKind.GROUP,         # band / solo project — group default
        EntityKind.ALBUM:       _MvEntityKind.OTHER,         # Work, not Entity
        EntityKind.RELEASE:     _MvEntityKind.OTHER,         # Work, not Entity
        EntityKind.TRACK:       _MvEntityKind.OTHER,         # Work, not Entity
        EntityKind.LABEL:       _MvEntityKind.ORGANISATION,
        EntityKind.CHANNEL:     _MvEntityKind.ORGANISATION,
        EntityKind.STUDIO:      _MvEntityKind.ORGANISATION,
        EntityKind.ACTOR:       _MvEntityKind.PERSON,
        EntityKind.VOICE_ACTOR: _MvEntityKind.PERSON,
        EntityKind.DIRECTOR:    _MvEntityKind.PERSON,
        EntityKind.PRODUCER:    _MvEntityKind.PERSON,
        EntityKind.COMPOSER:    _MvEntityKind.PERSON,
        EntityKind.WRITER:      _MvEntityKind.PERSON,
        EntityKind.NARRATOR:    _MvEntityKind.PERSON,
        EntityKind.HOST:        _MvEntityKind.PERSON,
        EntityKind.AUTHOR:      _MvEntityKind.PERSON,
        EntityKind.CHARACTER:   _MvEntityKind.PERSON,        # fictional person
        EntityKind.OTHER:       _MvEntityKind.OTHER,
    })
    _RELATION_ROLE.update({
        EntityKind.ACTOR:       _MvRelationRole.ACTOR,
        EntityKind.VOICE_ACTOR: _MvRelationRole.ACTOR,       # no separate VOICE_ACTOR in foundation
        EntityKind.DIRECTOR:    _MvRelationRole.DIRECTOR,
        EntityKind.PRODUCER:    _MvRelationRole.PRODUCER,    # NB: foundation PRODUCER is *music* producer
        EntityKind.COMPOSER:    _MvRelationRole.COMPOSER,
        EntityKind.WRITER:      _MvRelationRole.SCREENWRITER,
        EntityKind.NARRATOR:    _MvRelationRole.NARRATOR,
        EntityKind.HOST:        _MvRelationRole.HOST,
        EntityKind.AUTHOR:      _MvRelationRole.AUTHOR,
        EntityKind.LABEL:       _MvRelationRole.LABEL,
        EntityKind.STUDIO:      _MvRelationRole.PUBLISHER,
        EntityKind.CHANNEL:     _MvRelationRole.DISTRIBUTOR,
        EntityKind.ARTIST:      _MvRelationRole.PERFORMER,
    })


_build_bridges()


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
                or (str(ext.anilist_staff_id) if ext.anilist_staff_id else None)
                or (str(ext.mal_person_id) if ext.mal_person_id else None)
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
    if kind == EntityKind.VOICE_ACTOR:
        return ((str(ext.tmdb_person) if ext.tmdb_person else None)
                or ext.imdb_person
                or (str(ext.anilist_staff_id) if ext.anilist_staff_id else None)
                or (str(ext.mal_person_id) if ext.mal_person_id else None)
                or ext.wikidata)
    if kind == EntityKind.STUDIO:
        return ((str(ext.anilist_studio_id) if ext.anilist_studio_id else None)
                or (str(ext.mal_studio_id) if ext.mal_studio_id else None)
                or ext.wikidata)
    if kind == EntityKind.CHARACTER:
        return ((str(ext.anilist_character_id) if ext.anilist_character_id else None)
                or (str(ext.mal_character_id) if ext.mal_character_id else None))
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
        # Normalize before dedup so "The Beatles" and "the beatles" don't
        # create two separate alias entries.
        norm = _normalize_name(name)
        if norm == _normalize_name(self.name):
            return
        if any(_normalize_name(a) == norm for a in self.aliases):
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
