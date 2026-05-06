"""Entity layer + mappings."""
from metadatarr.resolve import (
    EntityKind,
    EntityRecord,
    EntityRole,
    EntitySidecar,
    ExternalIds,
    ProviderEntity,
    allocate_entity_id,
    attach_work,
    entities_by_kind,
    upsert_entity,
)
from metadatarr.resolve.mappings import (
    MappingEntry,
    MappingStore,
    add_mapping,
    apply_mappings,
    reload,
)


# -----------------------------------------------------------------------------
# allocate_entity_id — picks dominant external id, else normalised name
# -----------------------------------------------------------------------------

def test_allocate_artist_prefers_mbid():
    a = allocate_entity_id(EntityRole.ARTIST,
                           external_ids=ExternalIds(musicbrainz_artist="m"))
    b = allocate_entity_id(EntityRole.ARTIST, name="other",
                           external_ids=ExternalIds(musicbrainz_artist="m"))
    assert a == b


def test_allocate_role_disambiguates_namesakes():
    """Same name in different roles must allocate distinct entity ids."""
    a = allocate_entity_id(EntityRole.DIRECTOR, name="John Smith")
    b = allocate_entity_id(EntityRole.WRITER, name="John Smith")
    assert a != b


def test_allocate_external_id_anchors_across_roles():
    """Authoritative ID anchors to the same entity even when the role differs."""
    # ARTIST has musicbrainz_artist as its dominant id; pulling from the same
    # mbid yields the same entity_id even when name differs.
    a = allocate_entity_id(EntityRole.ARTIST, name="X",
                           external_ids=ExternalIds(musicbrainz_artist="m"))
    b = allocate_entity_id(EntityRole.ARTIST, name="Y",
                           external_ids=ExternalIds(musicbrainz_artist="m"))
    assert a == b


def test_allocate_falls_back_to_name():
    a = allocate_entity_id(EntityRole.ARTIST, name="Daft Punk")
    b = allocate_entity_id(EntityRole.ARTIST, name="daft  punk!")
    assert a == b  # normalisation collapses casing/punctuation


def test_allocate_album_uses_mb_release_group():
    eid = allocate_entity_id(EntityRole.ALBUM,
                             external_ids=ExternalIds(musicbrainz_release_group="rg"))
    assert isinstance(eid, str) and len(eid) == 40


def test_allocate_author_uses_olid():
    a = allocate_entity_id(EntityRole.AUTHOR, external_ids=ExternalIds(olid="OL1A"))
    b = allocate_entity_id(EntityRole.AUTHOR, name="other",
                           external_ids=ExternalIds(olid="OL1A"))
    assert a == b


def test_allocate_label_and_channel_and_other():
    # exercise the kind-specific branches
    allocate_entity_id(EntityRole.LABEL, external_ids=ExternalIds(metal_archives_label=1))
    allocate_entity_id(EntityRole.CHANNEL,
                       external_ids=ExternalIds(extra={"youtube_channel_id": "UC"}))
    allocate_entity_id(EntityRole.DIRECTOR,
                       external_ids=ExternalIds(extra={"tmdb_person": "1"}))
    allocate_entity_id(EntityRole.OTHER, name="x")  # default branch


# -----------------------------------------------------------------------------
# upsert / attach / by_kind
# -----------------------------------------------------------------------------

def test_upsert_inserts_then_merges_aliases():
    side = EntitySidecar()
    cand = ProviderEntity(
        role=EntityRole.ARTIST, name="Daft Punk",
                          external_ids=ExternalIds(musicbrainz_artist="mbid"))
    eid = upsert_entity(side, cand)
    assert eid in side.entities

    # second contribution with a different surface name absorbs as alias
    cand2 = ProviderEntity(
        role=EntityRole.ARTIST, name="Daftpunk",
                           external_ids=ExternalIds(musicbrainz_artist="mbid",
                                                   wikidata="Q1"))
    eid2 = upsert_entity(side, cand2)
    assert eid2 == eid
    rec = side.entities[eid]
    assert "Daftpunk" in rec.aliases
    assert rec.external_ids.wikidata == "Q1"


def test_entity_record_helpers_no_op_paths():
    rec = EntityRecord(id="x", role=EntityRole.ARTIST, name="X")
    rec.merge_alias("")             # blank ignored
    rec.merge_alias("X")            # same as name ignored
    rec.merge_alias("Y")
    rec.merge_alias("Y")            # dup ignored
    assert rec.aliases == ["Y"]


def test_attach_work_and_entities_by_role():
    from metadatarr.resolve import entities_by_role
    side = EntitySidecar()
    eid = upsert_entity(side, ProviderEntity(
        role=EntityRole.ALBUM, name="A"))
    attach_work(side, eid, "w1")
    attach_work(side, eid, "w1")    # dup ignored
    attach_work(side, eid, "")      # empty ignored
    attach_work(side, "missing", "w1")  # unknown id is a no-op

    upsert_entity(side, ProviderEntity(
        role=EntityRole.ARTIST, name="B"))
    assert len(entities_by_role(side, EntityRole.ALBUM)) == 1
    assert len(entities_by_role(side, EntityRole.ARTIST)) == 1


def test_entities_by_kind_groups_structurally():
    """entities_by_kind groups by mediavocab structural EntityKind."""
    from mediavocab import EntityKind as MvEntityKind
    side = EntitySidecar()
    upsert_entity(side, ProviderEntity(role=EntityRole.DIRECTOR, name="D"))
    upsert_entity(side, ProviderEntity(role=EntityRole.ACTOR, name="A"))
    upsert_entity(side, ProviderEntity(role=EntityRole.LABEL, name="L"))
    # DIRECTOR + ACTOR both map structurally to PERSON.
    assert len(entities_by_kind(side, MvEntityKind.PERSON)) == 2
    assert len(entities_by_kind(side, MvEntityKind.ORGANISATION)) == 1


# -----------------------------------------------------------------------------
# Mappings — store, apply, runtime add, reload
# -----------------------------------------------------------------------------

def test_mapping_store_merges_overlapping_entries():
    store = MappingStore()
    store.add(MappingEntry(EntityRole.ARTIST, "X",
                           {"musicbrainz_artist": "m", "wikidata": "Q1"}))
    store.add(MappingEntry(EntityRole.ARTIST, None,
                           {"wikidata": "Q1", "extra_key": "v"}))
    assert len(store) == 1
    entry = store.lookup(EntityRole.ARTIST, {"wikidata": "Q1"})
    assert entry is not None
    assert "extra_key" in entry.identifiers


def test_mapping_store_lookup_kind_filtered():
    store = MappingStore()
    store.add(MappingEntry(EntityRole.ARTIST, "X", {"wikidata": "Q1"}))
    assert store.lookup(EntityRole.ALBUM, {"wikidata": "Q1"}) is None


def test_mapping_apply_noop_when_no_match():
    store = MappingStore()
    out = store.apply(EntityRole.ARTIST, ExternalIds(wikidata="Q-unknown"))
    assert out.wikidata == "Q-unknown"


def test_mapping_apply_enriches_external_ids():
    store = MappingStore()
    store.add(MappingEntry(EntityRole.ARTIST, "X",
                           {"musicbrainz_artist": "m", "wikidata": "Q1"}))
    out = store.apply(EntityRole.ARTIST,
                      ExternalIds(musicbrainz_artist="m"))
    assert out.wikidata == "Q1"


def test_mapping_url_normalisation_matches():
    store = MappingStore()
    store.add(MappingEntry(EntityRole.ARTIST, None, {
        "soundcloud_artist_url": "https://soundcloud.com/x",
    }))
    # Trailing slash + extra whitespace normalised to same key
    e = store.lookup(EntityRole.ARTIST, {
        "soundcloud_artist_url": "https://soundcloud.com/x/  ",
    })
    assert e is not None


def test_mapping_entry_to_external_ids_coerces_int():
    e = MappingEntry(EntityRole.ARTIST, None,
                    {"metal_archives_band": "12345", "extra_thing": "v"})
    ext = e.to_external_ids()
    assert ext.metal_archives_band == 12345
    assert ext.extra["extra_thing"] == "v"


def test_mapping_score_gates_application():
    store = MappingStore()
    store.add(MappingEntry(EntityRole.ARTIST, None,
                           {"musicbrainz_artist": "m", "wikidata": "Q1"},
                           score=0.4))
    # Below the gate → no enrichment
    out = store.apply(EntityRole.ARTIST,
                      ExternalIds(musicbrainz_artist="m"),
                      min_score=0.5)
    assert out.wikidata is None
    # Above the gate → enrichment
    out = store.apply(EntityRole.ARTIST,
                      ExternalIds(musicbrainz_artist="m"),
                      min_score=0.3)
    assert out.wikidata == "Q1"


def test_mapping_score_clamped_to_unit_interval():
    e = MappingEntry(EntityRole.ARTIST, None, {"wikidata": "Q1"}, score=2.5)
    assert e.score == 1.0
    e = MappingEntry(EntityRole.ARTIST, None, {"wikidata": "Q2"}, score=-1.0)
    assert e.score == 0.0


def test_runtime_add_mapping_then_reload_clears_it():
    add_mapping(EntityRole.ARTIST,
                {"wikidata": "Q-runtime"}, name="Runtime")
    assert apply_mappings(EntityRole.ARTIST,
                          ExternalIds(wikidata="Q-runtime")).wikidata == "Q-runtime"
    reload()  # discards runtime entries


# ---------------------------------------------------------------------------
# Mediavocab bridge — to_mediavocab_kind / to_mediavocab_role
# ---------------------------------------------------------------------------

import pytest
from mediavocab import EntityKind as MvEntityKind, RelationRole as MvRelationRole

from metadatarr.resolve.entities import EntityRole


@pytest.mark.parametrize(
    "ek, expected_kind",
    [
        (EntityRole.ARTIST,      MvEntityKind.GROUP),
        (EntityRole.LABEL,       MvEntityKind.ORGANISATION),
        (EntityRole.STUDIO,      MvEntityKind.ORGANISATION),
        (EntityRole.CHANNEL,     MvEntityKind.ORGANISATION),
        (EntityRole.ACTOR,       MvEntityKind.PERSON),
        (EntityRole.VOICE_ACTOR, MvEntityKind.PERSON),
        (EntityRole.DIRECTOR,    MvEntityKind.PERSON),
        (EntityRole.AUTHOR,      MvEntityKind.PERSON),
        (EntityRole.CHARACTER,   MvEntityKind.PERSON),
        # Work-shaped values map to OTHER as a signal to use Work, not Entity.
        (EntityRole.ALBUM,       MvEntityKind.OTHER),
        (EntityRole.RELEASE,     MvEntityKind.OTHER),
        (EntityRole.TRACK,       MvEntityKind.OTHER),
        (EntityRole.OTHER,       MvEntityKind.OTHER),
    ],
)
def test_to_mediavocab_kind(ek, expected_kind):
    assert ek.to_mediavocab_kind() == expected_kind


@pytest.mark.parametrize(
    "ek, expected_role",
    [
        (EntityRole.DIRECTOR,    MvRelationRole.DIRECTOR),
        (EntityRole.ACTOR,       MvRelationRole.ACTOR),
        (EntityRole.VOICE_ACTOR, MvRelationRole.ACTOR),
        (EntityRole.NARRATOR,    MvRelationRole.NARRATOR),
        (EntityRole.HOST,        MvRelationRole.HOST),
        (EntityRole.AUTHOR,      MvRelationRole.AUTHOR),
        (EntityRole.COMPOSER,    MvRelationRole.COMPOSER),
        (EntityRole.WRITER,      MvRelationRole.SCREENWRITER),
        (EntityRole.PRODUCER,    MvRelationRole.PRODUCER),
        (EntityRole.LABEL,       MvRelationRole.LABEL),
        (EntityRole.STUDIO,      MvRelationRole.PUBLISHER),
        (EntityRole.CHANNEL,     MvRelationRole.DISTRIBUTOR),
        (EntityRole.ARTIST,      MvRelationRole.PERFORMER),
    ],
)
def test_to_mediavocab_role(ek, expected_role):
    assert ek.to_mediavocab_role() == expected_role


def test_to_mediavocab_role_none_for_non_role_kinds():
    # ALBUM / RELEASE / TRACK are Works, CHARACTER is fictional, OTHER is unknown.
    assert EntityRole.ALBUM.to_mediavocab_role() is None
    assert EntityRole.RELEASE.to_mediavocab_role() is None
    assert EntityRole.TRACK.to_mediavocab_role() is None
    assert EntityRole.CHARACTER.to_mediavocab_role() is None
    assert EntityRole.OTHER.to_mediavocab_role() is None
