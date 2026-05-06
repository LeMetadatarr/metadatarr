"""EntitySidecar persistence + reverse index."""
from metadatarr.resolve import (
    EntityKind,
    EntityRole,
    EntitySidecar,
    ExternalIds,
    ProviderEntity,
    upsert_entity,
)
from metadatarr.resolve.sidecar import (
    SidecarIndex,
    build_index,
    load,
    save,
)


def _populate(sidecar):
    upsert_entity(sidecar, ProviderEntity(
        role=EntityRole.ARTIST,
        name="Daft Punk",
        external_ids=ExternalIds(musicbrainz_artist="mbid-dp"),
    ))
    upsert_entity(sidecar, ProviderEntity(
        role=EntityRole.AUTHOR,
        name="J. R. R. Tolkien",
        external_ids=ExternalIds(olid="OL26320A",
                                 extra={"goodreads_author": "656983"}),
    ))


def test_save_and_load_roundtrips(tmp_path):
    src = EntitySidecar()
    _populate(src)
    out = tmp_path / "entities.json"
    save(src, out)
    assert out.exists()
    restored = load(out)
    assert restored.entities == src.entities


def test_load_missing_path_returns_empty(tmp_path):
    s = load(tmp_path / "nope.json")
    assert isinstance(s, EntitySidecar)
    assert s.entities == {}


def test_save_is_atomic_no_tempfiles_left(tmp_path):
    src = EntitySidecar()
    _populate(src)
    target = tmp_path / "entities.json"
    save(src, target)
    leftovers = [p.name for p in tmp_path.iterdir() if p != target]
    assert leftovers == []


def test_index_finds_entity_by_external_id():
    s = EntitySidecar()
    _populate(s)
    idx = build_index(s)
    eid = idx.find_by_external_id(EntityRole.ARTIST, "musicbrainz_artist",
                                  "mbid-dp")
    assert eid is not None
    assert s.entities[eid].name == "Daft Punk"


def test_index_finds_entity_by_extra_external_id():
    s = EntitySidecar()
    _populate(s)
    idx = build_index(s)
    eid = idx.find_by_external_id(EntityRole.AUTHOR, "goodreads_author",
                                  "656983")
    assert eid is not None
    assert s.entities[eid].name.startswith("J.")


def test_index_find_by_name_normalises():
    s = EntitySidecar()
    _populate(s)
    idx = build_index(s)
    matches = idx.find_by_name(EntityRole.ARTIST, "daft  punk!")
    assert len(matches) == 1


def test_index_returns_empty_for_unknown():
    idx = SidecarIndex()
    assert idx.find_by_external_id(EntityRole.ARTIST, "musicbrainz_artist", "x") is None
    assert idx.find_by_name(EntityRole.ARTIST, "nobody") == []
