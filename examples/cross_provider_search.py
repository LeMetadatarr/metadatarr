"""Cross-provider search demo.

`metadatarr.resolve.search(signals)` fans out to every active provider
that covers the signal's medium and returns the **ranked candidate union**
— no consolidation. Useful for:

- Building a "did you mean…?" UI list.
- Scoring candidates against an external model before picking.
- Inspecting per-provider disagreement before forcing one answer.

Pipeline equivalences::

    consolidate(search(signals), signals)  ==  resolve(signals)
    search(signals)[:5]                    ==  top-5 picks for a UI

Run it::

    METADATARR_TMDB_KEY=… python examples/cross_provider_search.py "Inception"

Without arguments, the script tries a couple of canonical queries.
"""
from __future__ import annotations

import sys

from metadatarr.resolve import (
    MediaType,
    Signals,
    active_providers,
    search,
)


DEFAULT_QUERIES = [
    ("Inception",  MediaType.MOVIE),
    ("The Boys",   MediaType.TV),
    ("Daft Punk",  MediaType.MUSIC),
]


def _print_candidates(query: str, medium: MediaType, candidates) -> None:
    print(f"\n{'=' * 78}")
    print(f"  {query}  ({medium.value})")
    print('=' * 78)
    if not candidates:
        active = ", ".join(p.name for p in active_providers(medium=medium))
        print(f"  no candidates returned (active providers for this medium: {active})")
        return
    for i, m in enumerate(candidates[:10], start=1):
        ids = m.external_ids.model_dump(exclude_none=True)
        ids.pop("extra", None)
        print(f"  {i:>2}. {m.provider:<14} confidence={m.confidence:.2f}  ids={ids}")


def main() -> None:
    queries = []
    if len(sys.argv) > 1:
        # Explicit query — assume movie unless caller cares to extend the script
        queries.append((" ".join(sys.argv[1:]), MediaType.MOVIE))
    else:
        queries = DEFAULT_QUERIES

    print("registered providers:",
          ", ".join(p.name for p in active_providers()))

    for title, medium in queries:
        candidates = search(Signals(title=title, medium=medium))
        _print_candidates(title, medium, candidates)


if __name__ == "__main__":
    main()
