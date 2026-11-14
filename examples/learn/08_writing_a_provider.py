"""Step 8 — write your own provider.

Subclass ``MetadataProvider``, implement ``is_available`` and
``lookup``, declare your three routing axes (``media``, ``playback_type``,
``genre_filter``), and call ``register()``. The resolver picks it up
on the next call.
"""
from typing import ClassVar, Optional, Set

from mediavocab import (
    MediaType, PlaybackType, Signals, ExternalIds,
)
from metadatarr.resolve import resolve
from metadatarr.resolve.base import (
    MetadataProvider, ProviderMatch, register,
)


class _LocalCatalogue(MetadataProvider):
    """Toy provider — looks up titles in a small in-memory table.

    A real provider would hit an HTTP API (httpx), parse the response
    into a ``ProviderMatch``, and return ``None`` when nothing matches.
    The structure stays the same.
    """

    name: ClassVar[str] = "local_catalogue"
    media: ClassVar[Set[MediaType]] = {MediaType.MOVIE}
    playback_type: ClassVar[Set[PlaybackType]] = {PlaybackType.VIDEO}

    _CATALOGUE = {
        "inception":    {"imdb": "tt1375666", "tmdb_movie": 27205, "year": 2010},
        "blade runner": {"imdb": "tt0083658", "tmdb_movie": 78,    "year": 1982},
    }

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        hit = self._CATALOGUE.get(signals.title.lower())
        if hit is None:
            return None
        return ProviderMatch(
            provider=self.name,
            confidence=0.95,                  # local data — high confidence
            signals=Signals(
                title=signals.title,
                year=hit["year"],
                medium=MediaType.MOVIE,
            ),
            external_ids=ExternalIds(
                imdb=hit["imdb"],
                tmdb_movie=hit["tmdb_movie"],
            ),
        )


def main() -> None:
    register(_LocalCatalogue())

    result = resolve(Signals(title="Inception", year=2010,
                             medium=MediaType.MOVIE,
                             playback_type=PlaybackType.VIDEO))

    print("Accepted matches (highest confidence first):")
    for m in result.accepted:
        print(f"  ✓ {m.provider:<18} confidence={m.confidence:.2f}")

    print(f"\nMerged ids:")
    print(f"  imdb       = {result.external_ids.imdb}")
    print(f"  tmdb_movie = {result.external_ids.tmdb_movie}")


if __name__ == "__main__":
    main()
