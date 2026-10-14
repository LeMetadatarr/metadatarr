"""Live integration test for the pymal + ARM cross-reference bridge.

Run from repo root:
    python metadatarr/examples/live/check_pymal.py
"""
from __future__ import annotations

import metadatarr.resolve.providers
from metadatarr.resolve.base import search, enrich
from metadatarr.resolve.providers.pymal import lookup_by_mal_id
from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals


def main() -> None:
    print("=== test 1: search returns mal_id + ARM cross-refs ===")
    results = search(Signals(
        title="Cowboy Bebop",
        medium=MediaType.EPISODIC_SERIES,
        content_genres=["anime"],
    ))
    pymal_match = next((m for m in results if m.provider == "pymal_anime"), None)
    if pymal_match:
        print("pymal_anime match:", pymal_match.external_ids)
    else:
        print("NOT FOUND")

    print()
    print("=== test 2: enrich(mal_id=1) fills anilist_id, anidb_id, imdb ===")
    e = enrich(ExternalIds(mal_id=1), medium=MediaType.EPISODIC_SERIES)
    print(f"mal_id={e.mal_id}  anilist_id={e.anilist_id}  anidb_id={e.anidb_id}  imdb={e.imdb}")

    print()
    print("=== test 3: enrich(mal_id=20) — Naruto ===")
    e2 = enrich(ExternalIds(mal_id=20), medium=MediaType.EPISODIC_SERIES)
    print(f"mal_id={e2.mal_id}  anilist_id={e2.anilist_id}  anidb_id={e2.anidb_id}")

    print()
    print("=== test 4: lookup_by_mal_id(1) entity relations ===")
    pm = lookup_by_mal_id(1)
    if pm:
        print(f"title={pm.signals.title}  confidence={pm.confidence}")
        print(f"external_ids={pm.external_ids}")
        for role, entities in pm.relations.items():
            print(f"  {role.value}: {[e.name for e in entities[:3]]}")
    else:
        print("FAILED")


if __name__ == "__main__":
    main()
