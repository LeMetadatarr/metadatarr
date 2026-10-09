"""Re-export shim for the pymal providers.

The four MyAnimeList-backed providers live in their own modules
(``pymal_anime.py``, ``pymal_manga.py``, ``pymal_person.py``,
``pymal_character.py``); shared helpers live in ``_pymal_common.py``. This
module only re-exports the public names so existing imports of
``metadatarr.resolve.providers.pymal`` keep working. It does not register
anything itself — each split module registers its own provider on import.
"""
from __future__ import annotations

from metadatarr.resolve.providers.pymal_anime import (
    PymalAnimeProvider,
    lookup_by_imdb,
    lookup_by_mal_id,
)
from metadatarr.resolve.providers.pymal_character import PymalCharacterProvider
from metadatarr.resolve.providers.pymal_manga import PymalMangaProvider
from metadatarr.resolve.providers.pymal_person import PymalPersonProvider

__all__ = [
    "PymalAnimeProvider",
    "PymalMangaProvider",
    "PymalPersonProvider",
    "PymalCharacterProvider",
    "lookup_by_mal_id",
    "lookup_by_imdb",
]

