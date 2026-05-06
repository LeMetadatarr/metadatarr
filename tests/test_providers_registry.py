"""Smoke tests: importing metadatarr.resolve registers the built-in providers."""
from metadatarr.resolve import all_providers


EXPECTED = {
    "skyhook",
    "musicbrainz",
    "audiodb",
    "tvmaze",
    "wikidata",
}


def test_built_in_providers_registered():
    names = set(all_providers())
    missing = EXPECTED - names
    assert not missing, f"expected providers missing from registry: {missing}"


def test_provider_classes_declare_metadata():
    for name, provider in all_providers().items():
        assert provider.name == name, f"{name}.name mismatch"
        assert hasattr(provider, "media")
        assert callable(provider.is_available)
        assert callable(provider.lookup)
