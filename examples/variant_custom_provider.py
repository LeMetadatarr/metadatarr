"""Write a custom list_variants() provider backed by a local JSON catalogue.

User story: "I maintain a personal database of known fanedits and director's
cuts in a JSON file. I want to plug it into the resolver so that any
resolve(..., include_variants=True) call automatically includes my local
entries alongside the IFDB results."

Demonstrates:
- Subclassing MetadataProvider and overriding list_variants()
- Registering the provider so resolve() picks it up automatically
- Structuring the returned ProviderEntity objects correctly
- No network required.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import List, Optional

import metadatarr.resolve.providers  # trigger built-in self-registration
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register, resolve
from metadatarr.resolve.entities import EntityKind, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType, VariantKind
from mediavocab.models.signals import Signals

# ---------------------------------------------------------------------------
# Sample local catalogue (normally you'd load this from a real file)
# ---------------------------------------------------------------------------
CATALOGUE = [
    {
        "imdb": "tt0133093",                   # The Matrix
        "title": "The Matrix: Fan Reconstruction",
        "variant_kind": "fanedit",
        "local_id": 1001,
        "notes": "Colour-graded to match the sequels",
    },
    {
        "imdb": "tt0133093",
        "title": "The Matrix: De-Greenified",
        "variant_kind": "fanedit",
        "local_id": 1002,
        "notes": "Removes the green colour cast from the Matrix scenes",
    },
    {
        "imdb": "tt0088763",                   # Back to the Future
        "title": "Back to the Future: Extended TV Cut",
        "variant_kind": "extended",
        "local_id": 1003,
        "notes": "Splices in the deleted scenes from the TV broadcast",
    },
]

_KIND_MAP = {k.value: k for k in VariantKind}


class LocalCatalogueProvider(MetadataProvider):
    """Variant-only provider backed by a local JSON file."""

    name = "local_catalogue"
    media = {MediaType.MOVIE}

    def __init__(self, catalogue: list) -> None:
        self._by_imdb: dict[str, list[dict]] = {}
        for entry in catalogue:
            self._by_imdb.setdefault(entry["imdb"], []).append(entry)

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None  # variant-only

    def list_variants(self, external_ids: ExternalIds,
                      signals: Optional[Signals] = None) -> List[ProviderEntity]:
        imdb = external_ids.imdb
        if not imdb or imdb not in self._by_imdb:
            return []
        out = []
        for entry in self._by_imdb[imdb]:
            vk = _KIND_MAP.get(entry.get("variant_kind", ""), VariantKind.OTHER)
            out.append(ProviderEntity(
                kind=EntityKind.RELEASE,
                name=entry["title"],
                external_ids=ExternalIds(
                    derived_from_imdb=imdb,
                    fanedit_id=entry.get("local_id"),
                ),
            ))
        return out


def main() -> None:
    # Register our custom provider — it will participate in all future
    # resolve() calls for medium=MOVIE with include_variants=True.
    provider = LocalCatalogueProvider(CATALOGUE)
    register(provider)

    print("=== resolve The Matrix with include_variants=True ===")
    from metadatarr.resolve.entities import Role

    result = resolve(Signals(
        title="The Matrix",
        year=1999,
        medium=MediaType.MOVIE,
        include_variants=True,
    ))

    print(f"  accepted providers : {[m.provider for m in result.accepted]}")
    print(f"  imdb               : {result.external_ids.imdb}")

    releases = result.relations.get(Role.RELEASE, [])
    local_releases = [
        r for r in releases
        if r.external_ids.fanedit_id and r.external_ids.fanedit_id >= 1000
    ]
    print(f"\n  total variants found  : {len(releases)}")
    print(f"  from local catalogue  : {len(local_releases)}")
    for r in local_releases:
        print(f"    local_id={r.external_ids.fanedit_id}  {r.name!r}")

    print("\n=== Back to the Future — only local catalogue has variants ===")
    result2 = resolve(Signals(
        title="Back to the Future",
        year=1985,
        medium=MediaType.MOVIE,
        include_variants=True,
    ))
    releases2 = result2.relations.get(Role.RELEASE, [])
    print(f"  variants: {len(releases2)}")
    for r in releases2:
        print(f"    {r.name!r}  fanedit_id={r.external_ids.fanedit_id}")


if __name__ == "__main__":
    main()
