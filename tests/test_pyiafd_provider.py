"""Tests for the IAFD metadatarr provider (offline, no network)."""
from __future__ import annotations

import pytest

from mediavocab.models import ExternalIds
from metadatarr.resolve.entities import EntityRole, ProviderEntity, allocate_entity_id, _dominant_external_id


# ---------------------------------------------------------------------------
# _dominant_external_id — iafd_performer_uuid in priority chain
# ---------------------------------------------------------------------------

class TestDominantExternalId:
    def test_iafd_uuid_used_as_dominant_for_actor(self):
        ext = ExternalIds(extra={"iafd_performer_uuid": "56125a4d-58ab-4170-84f0-391f19bb334b"})
        dom = _dominant_external_id(ext, EntityRole.ACTOR)
        assert dom == "56125a4d-58ab-4170-84f0-391f19bb334b"

    def test_tmdb_beats_iafd(self):
        ext = ExternalIds(
            tmdb_person=12345,
            extra={"iafd_performer_uuid": "56125a4d-58ab-4170-84f0-391f19bb334b"},
        )
        dom = _dominant_external_id(ext, EntityRole.ACTOR)
        assert dom == "12345"

    def test_imdb_beats_iafd(self):
        ext = ExternalIds(
            imdb_person="nm0001234",
            extra={"iafd_performer_uuid": "56125a4d-58ab-4170-84f0-391f19bb334b"},
        )
        dom = _dominant_external_id(ext, EntityRole.ACTOR)
        assert dom == "nm0001234"

    def test_no_iafd_uuid_falls_back_to_none(self):
        ext = ExternalIds(extra={"freeones_url": "https://www.freeones.com/misty-stone/bio"})
        dom = _dominant_external_id(ext, EntityRole.ACTOR)
        assert dom is None

    def test_iafd_uuid_used_for_director_role(self):
        ext = ExternalIds(extra={"iafd_performer_uuid": "abc-123"})
        dom = _dominant_external_id(ext, EntityRole.DIRECTOR)
        assert dom == "abc-123"

    def test_iafd_uuid_not_used_for_artist_role(self):
        ext = ExternalIds(extra={"iafd_performer_uuid": "abc-123"})
        dom = _dominant_external_id(ext, EntityRole.ARTIST)
        assert dom is None  # ARTIST role uses a different chain


# ---------------------------------------------------------------------------
# allocate_entity_id — UUID-stable entity IDs for adult performers
# ---------------------------------------------------------------------------

class TestAllocateEntityId:
    def test_same_uuid_gives_same_id(self):
        uuid = "56125a4d-58ab-4170-84f0-391f19bb334b"
        ext = ExternalIds(extra={"iafd_performer_uuid": uuid})
        id1 = allocate_entity_id(EntityRole.ACTOR, name="Misty Stone", external_ids=ext)
        id2 = allocate_entity_id(EntityRole.ACTOR, name="Misty Stone", external_ids=ext)
        assert id1 == id2

    def test_uuid_gives_different_id_from_name_only(self):
        uuid = "56125a4d-58ab-4170-84f0-391f19bb334b"
        ext = ExternalIds(extra={"iafd_performer_uuid": uuid})
        id_uuid = allocate_entity_id(EntityRole.ACTOR, name="Misty Stone", external_ids=ext)
        id_name = allocate_entity_id(EntityRole.ACTOR, name="Misty Stone", external_ids=ExternalIds())
        assert id_uuid != id_name

    def test_two_actors_same_name_same_uuid_same_entity_id(self):
        uuid = "56125a4d-58ab-4170-84f0-391f19bb334b"
        ext1 = ExternalIds(extra={"iafd_performer_uuid": uuid})
        ext2 = ExternalIds(extra={"iafd_performer_uuid": uuid, "freeones_url": "https://freeones.com/x"})
        id1 = allocate_entity_id(EntityRole.ACTOR, name="Misty Stone", external_ids=ext1)
        id2 = allocate_entity_id(EntityRole.ACTOR, name="Misty Stone", external_ids=ext2)
        assert id1 == id2  # same UUID → same entity

    def test_different_uuids_different_entity_ids(self):
        ext1 = ExternalIds(extra={"iafd_performer_uuid": "aaaa-1111"})
        ext2 = ExternalIds(extra={"iafd_performer_uuid": "bbbb-2222"})
        id1 = allocate_entity_id(EntityRole.ACTOR, name="John Smith", external_ids=ext1)
        id2 = allocate_entity_id(EntityRole.ACTOR, name="John Smith", external_ids=ext2)
        assert id1 != id2  # different UUIDs → different entities even with same name


# ---------------------------------------------------------------------------
# IAFDProvider — offline mocks
# ---------------------------------------------------------------------------

class _FakePerformer:
    id = "56125a4d-58ab-4170-84f0-391f19bb334b"
    name = "Misty Stone"
    url = "https://www.iafd.com/person.rme/id=56125a4d-..."
    birthday = "March 26, 1986"
    birth_year = 1986
    birthplace = "Inglewood, CA, USA"
    astrology = "Aries"
    gender = "Woman"
    active_from = 2006
    active_to = 2026
    aliases = ["Jenny Stone"]
    photo_url = "https://cdn.iafd.com/headshots/mistystone.jpg"
    stats = type("S", (), {
        "ethnicity": "Black/Native American",
        "nationality": "American",
        "height_cm": 165,
        "weight_kg": 55,
        "measurements": "32A-25-35",
        "hair_color": "Black",
        "eye_color": "Brown",
        "tattoos": None,
        "piercings": None,
    })()
    social = type("Soc", (), {
        "twitter": "https://twitter.com/mistystonexxx",
        "instagram": "https://www.instagram.com/mistystonethelegend",
        "onlyfans": "https://onlyfans.com/mistystone",
        "facebook": None,
    })()
    awards = []
    filmography = []
    comments = []


class _FakeCastMember:
    def __init__(self, name, uuid):
        self.name = name
        self.id = uuid
        self.headshot_url = ""
        self.role = ""
        self.url = ""


class _FakeTitle:
    id = "d9231537-e960-4009-97e7-3fd4982b301c"
    title = "Gloryhole Initiations: Misty Stone"
    year = "2006"
    url = "https://www.iafd.com/title.rme/id=d9231537-..."
    director = ""
    distributor = "Dogfart Network"
    studio = "gloryhole-initiations.com"
    runtime_minutes = 89
    release_date = "Sep 11, 2006"
    is_webscene = True
    is_all_girl = False
    is_all_male = False
    is_compilation = False
    cover_url = "https://cdn.iafd.com/cover.jpg"
    cast = [_FakeCastMember("Misty Stone", "56125a4d-58ab-4170-84f0-391f19bb334b")]


class _FakeSearchResult:
    def __init__(self, name, id_, year=None):
        self.name = name
        self.id = id_
        self.year = year


@pytest.fixture
def mock_pyiafd(monkeypatch):
    """Replace pyiafd network calls with fake returns."""
    import sys
    import types
    import pyiafd.ids as real_ids  # cache before replacing

    fake = types.ModuleType("pyiafd")
    fake.search_titles = lambda title: [
        _FakeSearchResult("Gloryhole Initiations: Misty Stone",
                          "d9231537-e960-4009-97e7-3fd4982b301c", "2006"),
    ]
    fake.get_title = lambda tid: _FakeTitle()
    fake.search_performers = lambda name: [
        _FakeSearchResult("Misty Stone", "56125a4d-58ab-4170-84f0-391f19bb334b"),
    ]
    fake.get_performer = lambda pid: _FakePerformer()
    # Preserve the ids submodule so `from pyiafd.ids import ...` still resolves
    fake.ids = real_ids

    original = sys.modules.get("pyiafd")
    original_ids = sys.modules.get("pyiafd.ids")
    sys.modules["pyiafd"] = fake
    sys.modules["pyiafd.ids"] = real_ids
    yield fake
    if original is None:
        sys.modules.pop("pyiafd", None)
    else:
        sys.modules["pyiafd"] = original
    if original_ids is None:
        sys.modules.pop("pyiafd.ids", None)
    else:
        sys.modules["pyiafd.ids"] = original_ids


class TestIAFDProvider:
    def test_is_available(self, mock_pyiafd):
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        assert IAFDProvider().is_available()

    def test_lookup_returns_match(self, mock_pyiafd):
        from mediavocab.models.signals import Signals
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        match = IAFDProvider().lookup(Signals(title="Gloryhole Initiations: Misty Stone", year=2006))
        assert match is not None

    def test_lookup_confidence_high(self, mock_pyiafd):
        from mediavocab.models.signals import Signals
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        match = IAFDProvider().lookup(Signals(title="Gloryhole Initiations: Misty Stone", year=2006))
        assert match.confidence >= 0.85

    def test_lookup_title_uuid_in_extra(self, mock_pyiafd):
        from mediavocab.models.signals import Signals
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        match = IAFDProvider().lookup(Signals(title="Gloryhole Initiations: Misty Stone"))
        assert match.external_ids.extra.get("iafd_title_uuid") == _FakeTitle.id

    def test_lookup_actor_relations(self, mock_pyiafd):
        from mediavocab.models.signals import Signals
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        match = IAFDProvider().lookup(Signals(title="Gloryhole Initiations: Misty Stone"))
        actors = match.relations.get(EntityRole.ACTOR, [])
        assert len(actors) == 1
        assert actors[0].name == "Misty Stone"
        assert actors[0].external_ids.extra.get("iafd_performer_uuid") == _FakeCastMember(
            "Misty Stone", "56125a4d-58ab-4170-84f0-391f19bb334b").id

    def test_lookup_studio_relation(self, mock_pyiafd):
        from mediavocab.models.signals import Signals
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        match = IAFDProvider().lookup(Signals(title="Gloryhole Initiations: Misty Stone"))
        studios = match.relations.get(EntityRole.STUDIO, [])
        assert len(studios) == 1
        assert studios[0].name == "Dogfart Network"

    def test_lookup_no_match_on_empty_results(self, mock_pyiafd):
        from mediavocab.models.signals import Signals
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        mock_pyiafd.search_titles = lambda t: []
        match = IAFDProvider().lookup(Signals(title="Unknown Title XYZ"))
        assert match is None

    def test_lookup_no_title_returns_none(self, mock_pyiafd):
        from mediavocab.models.signals import Signals
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        match = IAFDProvider().lookup(Signals(title=None))
        assert match is None

    def test_enrich_refetches_title(self, mock_pyiafd):
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        ext = ExternalIds(extra={"iafd_title_uuid": _FakeTitle.id})
        enriched = IAFDProvider().enrich(ext)
        assert enriched is not None
        assert enriched.extra.get("iafd_distributor") == "Dogfart Network"

    def test_enrich_skips_when_already_complete(self, mock_pyiafd):
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        ext = ExternalIds(extra={
            "iafd_title_uuid": _FakeTitle.id,
            "iafd_title_url": "https://...",
            "iafd_distributor": "Dogfart Network",
        })
        # Already has url + distributor — should skip re-fetch
        enriched = IAFDProvider().enrich(ext)
        assert enriched is None

    def test_enrich_returns_none_without_uuid(self, mock_pyiafd):
        from metadatarr.resolve.providers.pyiafd import IAFDProvider
        ext = ExternalIds(extra={"pornhub_vkey": "abc"})
        assert IAFDProvider().enrich(ext) is None


class TestEnrichPerformerEntity:
    def test_enriches_by_uuid(self, mock_pyiafd):
        from metadatarr.resolve.providers.pyiafd import enrich_performer_entity
        entity = ProviderEntity(
            role=EntityRole.ACTOR,
            name="Misty Stone",
            external_ids=ExternalIds(extra={"iafd_performer_uuid": "56125a4d-..."}),
        )
        result = enrich_performer_entity(entity)
        extra = result.external_ids.extra
        assert extra.get("iafd_birthday") == "March 26, 1986"
        assert extra.get("iafd_height_cm") == "165"
        assert extra.get("iafd_ethnicity") == "Black/Native American"
        assert "twitter" in extra.get("iafd_twitter", "")

    def test_enriches_by_name(self, mock_pyiafd):
        from metadatarr.resolve.providers.pyiafd import enrich_performer_entity
        entity = ProviderEntity(
            role=EntityRole.ACTOR,
            name="Misty Stone",
            external_ids=ExternalIds(),
        )
        result = enrich_performer_entity(entity)
        extra = result.external_ids.extra
        assert extra.get("iafd_performer_uuid") == "56125a4d-58ab-4170-84f0-391f19bb334b"
        assert extra.get("iafd_birthday") == "March 26, 1986"

    def test_no_match_returns_unchanged(self, mock_pyiafd):
        from metadatarr.resolve.providers.pyiafd import enrich_performer_entity
        mock_pyiafd.search_performers = lambda n: []
        entity = ProviderEntity(role=EntityRole.ACTOR, name="Nobody Special",
                                external_ids=ExternalIds())
        result = enrich_performer_entity(entity)
        assert result is entity  # unchanged

    def test_skip_when_already_enriched(self, mock_pyiafd):
        from metadatarr.resolve.providers.pyiafd import enrich_performer_entity
        call_count = 0
        original = mock_pyiafd.get_performer
        def counting_get(pid):
            nonlocal call_count
            call_count += 1
            return original(pid)
        mock_pyiafd.get_performer = counting_get

        entity = ProviderEntity(
            role=EntityRole.ACTOR,
            name="Misty Stone",
            external_ids=ExternalIds(extra={
                "iafd_performer_uuid": "56125a4d-58ab-4170-84f0-391f19bb334b",
                "iafd_birthday": "March 26, 1986",  # already enriched — UUID path skips
            }),
        )
        enrich_performer_entity(entity)
        assert call_count == 0  # should not re-fetch

    def test_entity_id_is_uuid_stable_after_enrichment(self, mock_pyiafd):
        from metadatarr.resolve.providers.pyiafd import enrich_performer_entity
        entity = ProviderEntity(
            role=EntityRole.ACTOR,
            name="Misty Stone",
            external_ids=ExternalIds(extra={"iafd_performer_uuid": "56125a4d-58ab-4170-84f0-391f19bb334b"}),
        )
        result = enrich_performer_entity(entity)
        eid = allocate_entity_id(result.role, name=result.name, external_ids=result.external_ids)
        # Should be UUID-based, not name-based
        eid_name = allocate_entity_id(EntityRole.ACTOR, name="Misty Stone", external_ids=ExternalIds())
        assert eid != eid_name
