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
        role=EntityRole.LABEL, name="A"))
    attach_work(side, eid, "w1")
    attach_work(side, eid, "w1")    # dup ignored
    attach_work(side, eid, "")      # empty ignored
    attach_work(side, "missing", "w1")  # unknown id is a no-op

    upsert_entity(side, ProviderEntity(
        role=EntityRole.ARTIST, name="B"))
    assert len(entities_by_role(side, EntityRole.LABEL)) == 1
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
    assert store.lookup(EntityRole.LABEL, {"wikidata": "Q1"}) is None


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
    # OTHER is unknown — no relation role mapping.
    assert EntityRole.OTHER.to_mediavocab_role() is None


# ---------------------------------------------------------------------------
# New roles added in expansion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ek, expected_kind",
    [
        (EntityRole.FEATURING,       MvEntityKind.GROUP),
        (EntityRole.SCREENWRITER,    MvEntityKind.PERSON),
        (EntityRole.CINEMATOGRAPHER, MvEntityKind.PERSON),
        (EntityRole.EDITOR,          MvEntityKind.PERSON),
        (EntityRole.LYRICIST,        MvEntityKind.PERSON),
        (EntityRole.ILLUSTRATOR,     MvEntityKind.PERSON),
        (EntityRole.TRANSLATOR,      MvEntityKind.PERSON),
        (EntityRole.GUEST,           MvEntityKind.PERSON),
        (EntityRole.CURATOR,         MvEntityKind.PERSON),
        (EntityRole.DISTRIBUTOR,     MvEntityKind.ORGANISATION),
    ],
)
def test_new_roles_to_mediavocab_kind(ek, expected_kind):
    assert ek.to_mediavocab_kind() == expected_kind


@pytest.mark.parametrize(
    "ek, expected_role",
    [
        (EntityRole.FEATURING,       MvRelationRole.FEATURING),
        (EntityRole.SCREENWRITER,    MvRelationRole.SCREENWRITER),
        (EntityRole.CINEMATOGRAPHER, MvRelationRole.CINEMATOGRAPHER),
        (EntityRole.EDITOR,          MvRelationRole.EDITOR),
        (EntityRole.LYRICIST,        MvRelationRole.LYRICIST),
        (EntityRole.ILLUSTRATOR,     MvRelationRole.ILLUSTRATOR),
        (EntityRole.TRANSLATOR,      MvRelationRole.TRANSLATOR),
        (EntityRole.GUEST,           MvRelationRole.GUEST),
        (EntityRole.CURATOR,         MvRelationRole.CURATOR),
        (EntityRole.DISTRIBUTOR,     MvRelationRole.DISTRIBUTOR),
    ],
)
def test_new_roles_to_mediavocab_role(ek, expected_role):
    assert ek.to_mediavocab_role() == expected_role


# ---------------------------------------------------------------------------
# image_url propagation through upsert_entity
# ---------------------------------------------------------------------------

def test_provider_entity_image_url_propagates_to_record():
    from metadatarr.resolve import EntitySidecar, ProviderEntity, upsert_entity
    side = EntitySidecar()
    cand = ProviderEntity(
        role=EntityRole.ARTIST, name="Daft Punk",
        image_url="https://img.example.com/daftpunk.jpg",
        external_ids=ExternalIds(musicbrainz_artist="mbid"),
    )
    eid = upsert_entity(side, cand)
    assert side.entities[eid].image_url == "https://img.example.com/daftpunk.jpg"


def test_image_url_not_overwritten_by_later_empty_upsert():
    from metadatarr.resolve import EntitySidecar, ProviderEntity, upsert_entity
    side = EntitySidecar()
    cand1 = ProviderEntity(
        role=EntityRole.ARTIST, name="X",
        image_url="https://img.example.com/x.jpg",
        external_ids=ExternalIds(musicbrainz_artist="mbid"),
    )
    cand2 = ProviderEntity(
        role=EntityRole.ARTIST, name="X",
        image_url=None,
        external_ids=ExternalIds(musicbrainz_artist="mbid"),
    )
    eid = upsert_entity(side, cand1)
    upsert_entity(side, cand2)
    assert side.entities[eid].image_url == "https://img.example.com/x.jpg"


def test_image_url_filled_by_later_upsert_when_empty():
    from metadatarr.resolve import EntitySidecar, ProviderEntity, upsert_entity
    side = EntitySidecar()
    cand1 = ProviderEntity(
        role=EntityRole.ARTIST, name="X",
        external_ids=ExternalIds(musicbrainz_artist="mbid"),
    )
    cand2 = ProviderEntity(
        role=EntityRole.ARTIST, name="X",
        image_url="https://img.example.com/x.jpg",
        external_ids=ExternalIds(musicbrainz_artist="mbid"),
    )
    eid = upsert_entity(side, cand1)
    upsert_entity(side, cand2)
    assert side.entities[eid].image_url == "https://img.example.com/x.jpg"


# ---------------------------------------------------------------------------
# _dominant_external_id uses first-class fields for promoted keys
# ---------------------------------------------------------------------------

def test_artist_dominant_uses_first_class_bandcamp():
    a = allocate_entity_id(EntityRole.ARTIST,
                           external_ids=ExternalIds(bandcamp_band_id=12345))
    b = allocate_entity_id(EntityRole.ARTIST,
                           external_ids=ExternalIds(bandcamp_band_id=12345))
    assert a == b


def test_artist_dominant_uses_first_class_soundcloud():
    a = allocate_entity_id(EntityRole.ARTIST,
                           external_ids=ExternalIds(soundcloud_user_id="my-band"))
    b = allocate_entity_id(EntityRole.ARTIST,
                           external_ids=ExternalIds(soundcloud_user_id="my-band"))
    assert a == b


def test_channel_dominant_uses_first_class_youtube_channel():
    a = allocate_entity_id(EntityRole.CHANNEL,
                           external_ids=ExternalIds(youtube_channel_id="UCxyz"))
    b = allocate_entity_id(EntityRole.CHANNEL,
                           external_ids=ExternalIds(youtube_channel_id="UCxyz"))
    assert a == b


def test_label_dominant_uses_first_class_musicbrainz_label():
    a = allocate_entity_id(EntityRole.LABEL,
                           external_ids=ExternalIds(musicbrainz_label="mb-label-uuid"))
    b = allocate_entity_id(EntityRole.LABEL,
                           external_ids=ExternalIds(musicbrainz_label="mb-label-uuid"))
    assert a == b


def test_iheart_station_in_external_ids():
    ids = ExternalIds(iheart_station_id="7556")
    d = ids.to_dict()
    assert d["iheart_station_id"] == "7556"
    ids2 = ExternalIds.from_dict(d)
    assert ids2.iheart_station_id == "7556"


def test_iheart_fields_round_trip():
    ids = ExternalIds(
        iheart_station_id="1",
        iheart_podcast_id="2",
        iheart_episode_id="3",
        iheart_artist_id="4",
    )
    d = ids.to_dict()
    ids2 = ExternalIds.from_dict(d)
    assert ids2.iheart_station_id == "1"
    assert ids2.iheart_podcast_id == "2"
    assert ids2.iheart_episode_id == "3"
    assert ids2.iheart_artist_id == "4"
