"""pymal module split: shim compatibility + single registration per provider.

``providers/pymal.py`` used to define all four MyAnimeList-backed providers
directly; they now live in ``pymal_anime.py``, ``pymal_manga.py``,
``pymal_person.py`` and ``pymal_character.py``, with shared helpers in
``_pymal_common.py``. ``pymal.py`` stays as a re-export shim so existing
imports keep working, and must not register anything itself.
"""
from __future__ import annotations

import metadatarr.resolve.providers  # noqa: F401 — triggers registration
from metadatarr.resolve.base import _REGISTRY


def test_old_import_path_still_works():
    from metadatarr.resolve.providers.pymal import (
        PymalAnimeProvider,
        PymalCharacterProvider,
        PymalMangaProvider,
        PymalPersonProvider,
        lookup_by_imdb,
        lookup_by_mal_id,
    )

    assert PymalAnimeProvider.name == "pymal_anime"
    assert PymalMangaProvider.name == "pymal_manga"
    assert PymalPersonProvider.name == "pymal_person"
    assert PymalCharacterProvider.name == "pymal_character"
    assert callable(lookup_by_mal_id)
    assert callable(lookup_by_imdb)


def test_split_modules_expose_same_classes_as_shim():
    from metadatarr.resolve.providers.pymal import PymalAnimeProvider as ShimAnime
    from metadatarr.resolve.providers.pymal_anime import PymalAnimeProvider as SplitAnime

    assert ShimAnime is SplitAnime


def test_four_pymal_providers_registered_exactly_once():
    for provider_name in ("pymal_anime", "pymal_manga", "pymal_person", "pymal_character"):
        assert provider_name in _REGISTRY
        # the registry is a plain dict keyed by name, so a duplicate
        # `register()` call for the same name would have overwritten rather
        # than duplicated — assert there is exactly one instance reachable
        # under that name and that it is the split module's class.
        instances = [v for k, v in _REGISTRY.items() if k == provider_name]
        assert len(instances) == 1


def test_registered_instances_come_from_split_modules_not_shim():
    from metadatarr.resolve.providers import pymal_anime, pymal_character, pymal_manga, pymal_person

    assert type(_REGISTRY["pymal_anime"]) is pymal_anime.PymalAnimeProvider
    assert type(_REGISTRY["pymal_manga"]) is pymal_manga.PymalMangaProvider
    assert type(_REGISTRY["pymal_person"]) is pymal_person.PymalPersonProvider
    assert type(_REGISTRY["pymal_character"]) is pymal_character.PymalCharacterProvider
