"""Identity rules for deduplicating resolved variants."""
from typing import List, Optional

import pytest

from metadatarr.resolve import (
    EntityRole,
    ExternalIds,
    MediaType,
    MetadataProvider,
    ProviderEntity,
    ProviderMatch,
    Signals,
    register,
    resolve,
)
from metadatarr.resolve import base as resolve_base
from metadatarr.resolve.base import _variant_key


@pytest.fixture
def registry(monkeypatch):
    """An empty provider registry for a test that registers its own providers: no
    real provider (pyfanedit searches fanedit.org) runs, and the registry is
    restored afterwards."""
    monkeypatch.setattr(resolve_base, "_REGISTRY", {})


def _variant(name: str, **ids) -> ProviderEntity:
    return ProviderEntity(role=EntityRole.OTHER, name=name, external_ids=ExternalIds(**ids))


def test_tmdb_only_variants_with_same_name_stay_distinct():
    a = _variant("Extended Cut", tmdb_person=101)
    b = _variant("Extended Cut", tmdb_person=202)
    assert _variant_key(a) != _variant_key(b)


def test_same_mb_release_different_names_dedupe():
    a = _variant("Deluxe Edition", musicbrainz_release="mbid-1")
    b = _variant("Deluxe (Bonus Disc)", musicbrainz_release="mbid-1")
    assert _variant_key(a) == _variant_key(b)


def test_fan_edits_of_one_film_are_not_keyed_by_the_film():
    a = _variant("Alien: FanFix", derived_from_imdb="tt0078748")
    b = _variant("Alien: TV Cut", derived_from_imdb="tt0078748")
    assert _variant_key(a) != _variant_key(b)
    assert _variant_key(a) == ("name", _variant_key(a)[1])


def test_fan_edits_sharing_a_title_are_told_apart_by_their_page():
    a = ProviderEntity(role=EntityRole.OTHER, name="Alien: Special",
                       external_ids=ExternalIds(derived_from_imdb="tt0078748",
                                                extra={"fanedit_url": "https://fanedit.org/a/", "faneditor": "One"}))
    b = ProviderEntity(role=EntityRole.OTHER, name="Alien: Special",
                       external_ids=ExternalIds(derived_from_imdb="tt0078748",
                                                extra={"fanedit_url": "https://fanedit.org/b/", "faneditor": "Two"}))
    assert _variant_key(a) != _variant_key(b)
    assert _variant_key(a) == _variant_key(a.model_copy(deep=True))


def test_no_ids_falls_back_to_normalized_name_case_insensitive():
    a = _variant("Director's Cut")
    b = _variant("  DIRECTOR'S   cut ")
    assert _variant_key(a) == _variant_key(b)
    assert _variant_key(a) == ("name", _variant_key(a)[1])


def test_seeded_variants_dedupe_against_fan_out_results(registry):
    seeded = _variant("Fan Edit", fanedit_id=1)

    class _SeededMatchProvider(MetadataProvider):
        name = "seeded_match"
        media: set = set()

        def is_available(self) -> bool:
            return True

        def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
            return ProviderMatch(
                provider=self.name,
                confidence=0.9,
                signals=signals,
                external_ids=ExternalIds(tmdb_movie=1),
                variants=[seeded],
            )

    class _FanOutProvider(MetadataProvider):
        name = "fan_out"
        media: set = set()

        def is_available(self) -> bool:
            return True

        def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
            return None

        def list_variants(self, external_ids: ExternalIds,
                          signals: Optional[Signals] = None) -> List[ProviderEntity]:
            return [_variant("Fan Edit (renamed)", fanedit_id=1)]

    register(_SeededMatchProvider())
    register(_FanOutProvider())

    signals = Signals(title="Some Movie", medium=MediaType.MOVIE, include_variants=True)
    result = resolve(signals)

    assert len(result.variants) == 1


def test_two_records_of_one_fan_edit_merge_whether_or_not_both_carry_the_page():
    a = _variant("Alien: Special", fanedit_id="1234")
    b = ProviderEntity(role=EntityRole.OTHER, name="Alien: Special",
                       external_ids=ExternalIds(fanedit_id="1234", extra={"fanedit_url": "https://fanedit.org/a/"}))
    assert _variant_key(a) == _variant_key(b) == ("fanedit_id", 1234)
