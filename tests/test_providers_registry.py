"""Smoke tests: importing metadatarr.resolve registers the built-in providers."""
from mediavocab import MediaType, PlaybackModality
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


def test_every_provider_declares_modality():
    """Every registered provider must declare ``modality`` (axiom 13).

    Empty set is allowed (universal); the test only enforces shape — that
    the attribute exists, is iterable, and contains only PlaybackModality
    values. A silent default at the ABC level still counts.
    """
    for name, provider in all_providers().items():
        assert hasattr(provider, "modality"), f"{name} missing modality"
        mods = provider.modality
        for m in mods:
            assert isinstance(m, PlaybackModality), (
                f"{name}.modality contains non-PlaybackModality: {m!r}"
            )


def test_audio_provider_excludes_video_signals():
    """Sanity: a known audio-only provider rejects a VIDEO query.

    Skipped if musicbrainz isn't registered (would mean the registry
    test above already failed)."""
    from mediavocab.models.signals import Signals
    mb = all_providers().get("musicbrainz")
    if mb is None:
        return
    audio_sig = Signals(title="x", medium=MediaType.MUSIC,
                        modality=PlaybackModality.AUDIO)
    video_sig = Signals(title="x", medium=MediaType.MUSIC,
                        modality=PlaybackModality.VIDEO)
    assert mb.matches(audio_sig) is True
    assert mb.matches(video_sig) is False
