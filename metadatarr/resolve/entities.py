"""Entity layer — typed structural kind + role taxonomy.

Two enums, separate concerns:

- :class:`EntityKind` — structural kind, re-exported from
  ``mediavocab.EntityKind`` (PERSON / GROUP / ORGANISATION / SERIES /
  DEVICE / OTHER). Tells you what *shape* of entity record you are
  looking at.
- :class:`EntityRole` — relational role, the resolver-internal
  taxonomy used to key :attr:`ProviderMatch.relations`. Tells you
  what role the entity plays in a particular work
  (director / actor / composer / label / studio / …). Carries only
  contribution roles — work-shaped emissions (release variants) live
  on :attr:`ProviderMatch.variants` instead.

A :class:`ProviderEntity` carries both: ``role`` is required (it is
how the provider classifies the contribution), ``kind`` is optional
and auto-derived from ``role.to_mediavocab_kind()`` if omitted.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Re-export the canonical structural kind from mediavocab.
from mediavocab import EntityKind, RelationRole
from mediavocab.models import ExternalIds


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EntityRole(str, Enum):
    """Resolver-internal role taxonomy used to key
    :attr:`ProviderMatch.relations`.

    Carries only contribution roles (``DIRECTOR``, ``ACTOR``,
    ``COMPOSER``, …). Work-shaped emissions (release variants) live
    on :attr:`ProviderMatch.variants` rather than as a relation role.
    Callers building canonical :class:`mediavocab.Entity` /
    :class:`mediavocab.Credit` records should map through
    :meth:`to_mediavocab_kind` and :meth:`to_mediavocab_role`.
    """

    # People / contributors
    ACTOR = "actor"
    VOICE_ACTOR = "voice_actor"
    DIRECTOR = "director"
    PRODUCER = "producer"
    COMPOSER = "composer"
    WRITER = "writer"
    NARRATOR = "narrator"
    HOST = "host"
    AUTHOR = "author"

    # Performance / recording
    ARTIST = "artist"

    # Organisations
    LABEL = "label"
    CHANNEL = "channel"
    STUDIO = "studio"

    OTHER = "other"

    def to_mediavocab_kind(self) -> EntityKind:
        """Return the structural ``mediavocab.EntityKind``."""
        return _STRUCTURAL_KIND.get(self, EntityKind.OTHER)

    def to_mediavocab_role(self) -> Optional[RelationRole]:
        """Return the typed ``mediavocab.RelationRole`` for this role,
        or ``None`` when this is not a contribution role."""
        return _RELATION_ROLE.get(self)


_STRUCTURAL_KIND: Dict[EntityRole, EntityKind] = {
    EntityRole.ARTIST:      EntityKind.GROUP,        # band / solo project — group default
    EntityRole.LABEL:       EntityKind.ORGANISATION,
    EntityRole.CHANNEL:     EntityKind.ORGANISATION,
    EntityRole.STUDIO:      EntityKind.ORGANISATION,
    EntityRole.ACTOR:       EntityKind.PERSON,
    EntityRole.VOICE_ACTOR: EntityKind.PERSON,
    EntityRole.DIRECTOR:    EntityKind.PERSON,
    EntityRole.PRODUCER:    EntityKind.PERSON,
    EntityRole.COMPOSER:    EntityKind.PERSON,
    EntityRole.WRITER:      EntityKind.PERSON,
    EntityRole.NARRATOR:    EntityKind.PERSON,
    EntityRole.HOST:        EntityKind.PERSON,
    EntityRole.AUTHOR:      EntityKind.PERSON,
    EntityRole.OTHER:       EntityKind.OTHER,
}

_RELATION_ROLE: Dict[EntityRole, RelationRole] = {
    EntityRole.ACTOR:       RelationRole.ACTOR,
    EntityRole.VOICE_ACTOR: RelationRole.ACTOR,         # foundation has no separate VOICE_ACTOR
    EntityRole.DIRECTOR:    RelationRole.DIRECTOR,
    EntityRole.PRODUCER:    RelationRole.PRODUCER,      # NB: foundation PRODUCER is *music* producer
    EntityRole.COMPOSER:    RelationRole.COMPOSER,
    EntityRole.WRITER:      RelationRole.SCREENWRITER,
    EntityRole.NARRATOR:    RelationRole.NARRATOR,
    EntityRole.HOST:        RelationRole.HOST,
    EntityRole.AUTHOR:      RelationRole.AUTHOR,
    EntityRole.LABEL:       RelationRole.LABEL,
    EntityRole.STUDIO:      RelationRole.PUBLISHER,
    EntityRole.CHANNEL:     RelationRole.DISTRIBUTOR,
    EntityRole.ARTIST:      RelationRole.PERFORMER,
}


def _normalize_name(name: str) -> str:
    name = (name or "").lower()
    name = re.sub(r"[\W_]+", " ", name, flags=re.UNICODE)
    return " ".join(name.split())


def _dominant_external_id(ext: ExternalIds, role: EntityRole) -> Optional[str]:
    """Return the most stable external id we know for ``role``."""
    if role == EntityRole.ARTIST:
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
    if role in {EntityRole.ACTOR, EntityRole.DIRECTOR, EntityRole.PRODUCER,
                EntityRole.COMPOSER, EntityRole.WRITER, EntityRole.NARRATOR,
                EntityRole.HOST}:
        # iafd_performer_uuid is authoritative for adult-industry performers
        # (no TMDB/IMDB equivalent exists for most of them)
        return ((str(ext.tmdb_person) if ext.tmdb_person else None)
                or ext.imdb_person
                or (str(ext.anilist_staff_id) if ext.anilist_staff_id else None)
                or (str(ext.mal_person_id) if ext.mal_person_id else None)
                or (str(ext.metal_archives_artist) if ext.metal_archives_artist else None)
                or ext.wikidata
                or ext.extra.get("tmdb_person")
                or ext.extra.get("imdb_person")
                or ext.extra.get("iafd_performer_uuid"))
    if role == EntityRole.AUTHOR:
        return (ext.olid or ext.goodreads or ext.extra.get("goodreads_author")
                or ext.wikidata)
    if role == EntityRole.LABEL:
        return ((str(ext.metal_archives_label) if ext.metal_archives_label else None)
                or ext.extra.get("musicbrainz_label") or ext.wikidata)
    if role == EntityRole.CHANNEL:
        return ext.extra.get("youtube_channel_id")
    if role == EntityRole.VOICE_ACTOR:
        return ((str(ext.tmdb_person) if ext.tmdb_person else None)
                or ext.imdb_person
                or (str(ext.anilist_staff_id) if ext.anilist_staff_id else None)
                or (str(ext.mal_person_id) if ext.mal_person_id else None)
                or ext.wikidata)
    if role == EntityRole.STUDIO:
        return ((str(ext.anilist_studio_id) if ext.anilist_studio_id else None)
                or (str(ext.mal_studio_id) if ext.mal_studio_id else None)
                or ext.wikidata)
    return None


def allocate_entity_id(role: EntityRole, *, name: str = "",
                       external_ids: Optional[ExternalIds] = None) -> str:
    """Deterministic entity id from external ids (preferred) or
    normalized name + role.

    When *external_ids* identify the entity unambiguously the role is
    not mixed into the seed — the same authoritative ID always points
    to the same person/group, even if they wear different hats on
    different works. When we fall back to the name-based seed, *role*
    is mixed in: two unrelated "John Smith" entries appearing in
    DIRECTOR vs WRITER roles must not collapse to the same entity.
    """
    ext = external_ids or ExternalIds()
    dom = _dominant_external_id(ext, role)
    if dom:
        seed = f"{role.value}|ext:{dom}"
    else:
        seed = f"{role.value}|name:{_normalize_name(name)}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


class ProviderEntity(BaseModel):
    """One entity contribution from a single provider response.

    ``role`` is the contribution category (DIRECTOR / ACTOR / LABEL /
    …); ``kind`` is the structural ``mediavocab.EntityKind`` of the
    underlying entity (PERSON / GROUP / ORGANISATION / …) and
    auto-derives from ``role.to_mediavocab_kind()`` when omitted.
    """

    model_config = ConfigDict(extra="forbid")

    role: EntityRole
    kind: Optional[EntityKind] = None
    name: str
    external_ids: ExternalIds = Field(default_factory=ExternalIds)

    @model_validator(mode="after")
    def _validate_kind_matches_role(self) -> "ProviderEntity":
        expected = self.role.to_mediavocab_kind()
        if self.kind is None:
            self.kind = expected
        elif self.kind != expected:
            raise ValueError(
                f"ProviderEntity kind={self.kind} disagrees with role={self.role} "
                f"(expected kind={expected}). Pass only one or make them agree."
            )
        return self


class EntityRecord(BaseModel):
    """One entry per *entity* in an entities sidecar."""

    model_config = ConfigDict(extra="forbid")

    id: str
    role: EntityRole
    kind: Optional[EntityKind] = None
    name: str
    aliases: List[str] = Field(default_factory=list)
    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    members: List[str] = Field(default_factory=list)  # sub-entity ids
    works: List[str] = Field(default_factory=list)    # work ids this entity participates in
    first_seen: str = Field(default_factory=_utcnow)
    last_updated: str = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _validate_kind_matches_role(self) -> "EntityRecord":
        expected = self.role.to_mediavocab_kind()
        if self.kind is None:
            self.kind = expected
        elif self.kind != expected:
            raise ValueError(
                f"EntityRecord kind={self.kind} disagrees with role={self.role} "
                f"(expected kind={expected}). Pass only one or make them agree."
            )
        return self

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

def upsert_entity(sidecar: EntitySidecar, candidate: ProviderEntity) -> str:
    """Insert or update a :class:`ProviderEntity`; return its
    ``entity_id``.

    Conservative merge: external-id-anchored records absorb new
    aliases / external_ids; otherwise the entity_id is derived from
    the normalized name + role.
    """
    eid = allocate_entity_id(candidate.role, name=candidate.name,
                             external_ids=candidate.external_ids)
    rec = sidecar.entities.get(eid)
    if rec is None:
        rec = EntityRecord(
            id=eid,
            role=candidate.role,
            kind=candidate.kind,
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


def entities_by_role(sidecar: EntitySidecar, role: EntityRole) -> List[EntityRecord]:
    return [r for r in sidecar.entities.values() if r.role == role]


def entities_by_kind(sidecar: EntitySidecar, kind: EntityKind) -> List[EntityRecord]:
    return [r for r in sidecar.entities.values() if r.kind == kind]
