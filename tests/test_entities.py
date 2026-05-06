"""Entity layer + mappings."""
from metadatarr.resolve import (
    EntityKind,
    EntityRecord,
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
    a = allocate_entity_id(EntityKind.ARTIST,
                           external_ids=ExternalIds(musicbrainz_artist="m"))
    b = allocate_entity_id(EntityKind.ARTIST, name="other",
                           external_ids=ExternalIds(musicbrainz_artist="m"))
    assert a == b


def test_allocate_role_disambiguates_namesakes():
    """Same name in different roles must allocate distinct entity ids."""
    a = allocate_entity_id(EntityKind.OTHER, name="John Smith",
                           role=EntityKind.DIRECTOR)
    b = allocate_entity_id(EntityKind.OTHER, name="John Smith",
                           role=EntityKind.WRITER)
    assert a != b


def test_allocate_role_ignored_when_external_id_present():
    """Authoritative ID anchors the entity regardless of role."""
    a = allocate_entity_id(EntityKind.ARTIST, name="X",
                           external_ids=ExternalIds(musicbrainz_artist="m"),
                           role=EntityKind.DIRECTOR)
    b = allocate_entity_id(EntityKind.ARTIST, name="X",
                           external_ids=ExternalIds(musicbrainz_artist="m"),
                           role=EntityKind.WRITER)
    assert a == b


def test_allocate_falls_back_to_name():
    a = allocate_entity_id(EntityKind.ARTIST, name="Daft Punk")
    b = allocate_entity_id(EntityKind.ARTIST, name="daft  punk!")
    assert a == b  # normalisation collapses casing/punctuation


def test_allocate_album_uses_mb_release_group():
    eid = allocate_entity_id(EntityKind.ALBUM,
                             external_ids=ExternalIds(musicbrainz_release_group="rg"))
    assert isinstance(eid, str) and len(eid) == 40


def test_allocate_author_uses_olid():
    a = allocate_entity_id(EntityKind.AUTHOR, external_ids=ExternalIds(olid="OL1A"))
    b = allocate_entity_id(EntityKind.AUTHOR, name="other",
                           external_ids=ExternalIds(olid="OL1A"))
    assert a == b


def test_allocate_label_and_channel_and_other():
    # exercise the kind-specific branches
    allocate_entity_id(EntityKind.LABEL, external_ids=ExternalIds(metal_archives_label=1))
    allocate_entity_id(EntityKind.CHANNEL,
                       external_ids=ExternalIds(extra={"youtube_channel_id": "UC"}))
    allocate_entity_id(EntityKind.DIRECTOR,
                       external_ids=ExternalIds(extra={"tmdb_person": "1"}))
    allocate_entity_id(EntityKind.OTHER, name="x")  # default branch


# -----------------------------------------------------------------------------
# upsert / attach / by_kind
# -----------------------------------------------------------------------------

def test_upsert_inserts_then_merges_aliases():
    side = EntitySidecar()
    cand = ProviderEntity(kind=EntityKind.ARTIST, name="Daft Punk",
                          external_ids=ExternalIds(musicbrainz_artist="mbid"))
    eid = upsert_entity(side, cand)
    assert eid in side.entities

    # second contribution with a different surface name absorbs as alias
    cand2 = ProviderEntity(kind=EntityKind.ARTIST, name="Daftpunk",
                           external_ids=ExternalIds(musicbrainz_artist="mbid",
                                                   wikidata="Q1"))
    eid2 = upsert_entity(side, cand2)
    assert eid2 == eid
    rec = side.entities[eid]
    assert "Daftpunk" in rec.aliases
    assert rec.external_ids.wikidata == "Q1"


def test_entity_record_helpers_no_op_paths():
    rec = EntityRecord(id="x", kind=EntityKind.ARTIST, name="X")
    rec.merge_alias("")             # blank ignored
    rec.merge_alias("X")            # same as name ignored
    rec.merge_alias("Y")
    rec.merge_alias("Y")            # dup ignored
    assert rec.aliases == ["Y"]


def test_attach_work_and_entities_by_kind():
    side = EntitySidecar()
    eid = upsert_entity(side, ProviderEntity(kind=EntityKind.ALBUM, name="A"))
    attach_work(side, eid, "w1")
    attach_work(side, eid, "w1")    # dup ignored
    attach_work(side, eid, "")      # empty ignored
    attach_work(side, "missing", "w1")  # unknown id is a no-op

    upsert_entity(side, ProviderEntity(kind=EntityKind.ARTIST, name="B"))
    assert len(entities_by_kind(side, EntityKind.ALBUM)) == 1
    assert len(entities_by_kind(side, EntityKind.ARTIST)) == 1


# -----------------------------------------------------------------------------
# Mappings — store, apply, runtime add, reload
# -----------------------------------------------------------------------------

def test_mapping_store_merges_overlapping_entries():
    store = MappingStore()
    store.add(MappingEntry(EntityKind.ARTIST, "X",
                           {"musicbrainz_artist": "m", "wikidata": "Q1"}))
    store.add(MappingEntry(EntityKind.ARTIST, None,
                           {"wikidata": "Q1", "extra_key": "v"}))
    assert len(store) == 1
    entry = store.lookup(EntityKind.ARTIST, {"wikidata": "Q1"})
    assert entry is not None
    assert "extra_key" in entry.identifiers


def test_mapping_store_lookup_kind_filtered():
    store = MappingStore()
    store.add(MappingEntry(EntityKind.ARTIST, "X", {"wikidata": "Q1"}))
    assert store.lookup(EntityKind.ALBUM, {"wikidata": "Q1"}) is None


def test_mapping_apply_noop_when_no_match():
    store = MappingStore()
    out = store.apply(EntityKind.ARTIST, ExternalIds(wikidata="Q-unknown"))
    assert out.wikidata == "Q-unknown"


def test_mapping_apply_enriches_external_ids():
    store = MappingStore()
    store.add(MappingEntry(EntityKind.ARTIST, "X",
                           {"musicbrainz_artist": "m", "wikidata": "Q1"}))
    out = store.apply(EntityKind.ARTIST,
                      ExternalIds(musicbrainz_artist="m"))
    assert out.wikidata == "Q1"


def test_mapping_url_normalisation_matches():
    store = MappingStore()
    store.add(MappingEntry(EntityKind.ARTIST, None, {
        "soundcloud_artist_url": "https://soundcloud.com/x",
    }))
    # Trailing slash + extra whitespace normalised to same key
    e = store.lookup(EntityKind.ARTIST, {
        "soundcloud_artist_url": "https://soundcloud.com/x/  ",
    })
    assert e is not None


def test_mapping_entry_to_external_ids_coerces_int():
    e = MappingEntry(EntityKind.ARTIST, None,
                    {"metal_archives_band": "12345", "extra_thing": "v"})
    ext = e.to_external_ids()
    assert ext.metal_archives_band == 12345
    assert ext.extra["extra_thing"] == "v"


def test_mapping_score_gates_application():
    store = MappingStore()
    store.add(MappingEntry(EntityKind.ARTIST, None,
                           {"musicbrainz_artist": "m", "wikidata": "Q1"},
                           score=0.4))
    # Below the gate → no enrichment
    out = store.apply(EntityKind.ARTIST,
                      ExternalIds(musicbrainz_artist="m"),
                      min_score=0.5)
    assert out.wikidata is None
    # Above the gate → enrichment
    out = store.apply(EntityKind.ARTIST,
                      ExternalIds(musicbrainz_artist="m"),
                      min_score=0.3)
    assert out.wikidata == "Q1"


def test_mapping_score_clamped_to_unit_interval():
    e = MappingEntry(EntityKind.ARTIST, None, {"wikidata": "Q1"}, score=2.5)
    assert e.score == 1.0
    e = MappingEntry(EntityKind.ARTIST, None, {"wikidata": "Q2"}, score=-1.0)
    assert e.score == 0.0


def test_runtime_add_mapping_then_reload_clears_it():
    add_mapping(EntityKind.ARTIST,
                {"wikidata": "Q-runtime"}, name="Runtime")
    assert apply_mappings(EntityKind.ARTIST,
                          ExternalIds(wikidata="Q-runtime")).wikidata == "Q-runtime"
    reload()  # discards runtime entries


# ---------------------------------------------------------------------------
# Mediavocab bridge — to_mediavocab_kind / to_mediavocab_role
# ---------------------------------------------------------------------------

import pytest
from mediavocab import EntityKind as MvEntityKind, RelationRole as MvRelationRole

from metadatarr.resolve.entities import EntityKind


@pytest.mark.parametrize(
    "ek, expected_kind",
    [
        (EntityKind.ARTIST,      MvEntityKind.GROUP),
        (EntityKind.LABEL,       MvEntityKind.ORGANISATION),
        (EntityKind.STUDIO,      MvEntityKind.ORGANISATION),
        (EntityKind.CHANNEL,     MvEntityKind.ORGANISATION),
        (EntityKind.ACTOR,       MvEntityKind.PERSON),
        (EntityKind.VOICE_ACTOR, MvEntityKind.PERSON),
        (EntityKind.DIRECTOR,    MvEntityKind.PERSON),
        (EntityKind.AUTHOR,      MvEntityKind.PERSON),
        (EntityKind.CHARACTER,   MvEntityKind.PERSON),
        # Work-shaped values map to OTHER as a signal to use Work, not Entity.
        (EntityKind.ALBUM,       MvEntityKind.OTHER),
        (EntityKind.RELEASE,     MvEntityKind.OTHER),
        (EntityKind.TRACK,       MvEntityKind.OTHER),
        (EntityKind.OTHER,       MvEntityKind.OTHER),
    ],
)
def test_to_mediavocab_kind(ek, expected_kind):
    assert ek.to_mediavocab_kind() == expected_kind


@pytest.mark.parametrize(
    "ek, expected_role",
    [
        (EntityKind.DIRECTOR,    MvRelationRole.DIRECTOR),
        (EntityKind.ACTOR,       MvRelationRole.ACTOR),
        (EntityKind.VOICE_ACTOR, MvRelationRole.ACTOR),
        (EntityKind.NARRATOR,    MvRelationRole.NARRATOR),
        (EntityKind.HOST,        MvRelationRole.HOST),
        (EntityKind.AUTHOR,      MvRelationRole.AUTHOR),
        (EntityKind.COMPOSER,    MvRelationRole.COMPOSER),
        (EntityKind.WRITER,      MvRelationRole.SCREENWRITER),
        (EntityKind.PRODUCER,    MvRelationRole.PRODUCER),
        (EntityKind.LABEL,       MvRelationRole.LABEL),
        (EntityKind.STUDIO,      MvRelationRole.PUBLISHER),
        (EntityKind.CHANNEL,     MvRelationRole.DISTRIBUTOR),
        (EntityKind.ARTIST,      MvRelationRole.PERFORMER),
    ],
)
def test_to_mediavocab_role(ek, expected_role):
    assert ek.to_mediavocab_role() == expected_role


def test_to_mediavocab_role_none_for_non_role_kinds():
    # ALBUM / RELEASE / TRACK are Works, CHARACTER is fictional, OTHER is unknown.
    assert EntityKind.ALBUM.to_mediavocab_role() is None
    assert EntityKind.RELEASE.to_mediavocab_role() is None
    assert EntityKind.TRACK.to_mediavocab_role() is None
    assert EntityKind.CHARACTER.to_mediavocab_role() is None
    assert EntityKind.OTHER.to_mediavocab_role() is None
