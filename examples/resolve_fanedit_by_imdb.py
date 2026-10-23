"""Look up all fanedits for a film you already have an IMDb id for.

User story: "I finished resolving a movie and got back its IMDb id. Now I want
to enumerate every fanedit IFDB has for it without doing a second full
resolve."

This example shows two paths:
  1. via resolve() with include_variants=True and a pre-known IMDb id seeded
     into ExternalIds directly (skips the lookup phase, uses enrich + variants)
  2. via the pyfanedit provider's list_variants() called manually, for cases
     where you already have all the IDs you need.

Requires:
    pip install metadatarr   # pyfanedit is a core dependency, no extra needed
"""
import metadatarr.resolve.providers  # trigger provider self-registration
from metadatarr.resolve.base import all_providers, enrich
from mediavocab.models import ExternalIds
from mediavocab import MediaType
from mediavocab.models.signals import Signals

# --- Star Wars: A New Hope ---
KNOWN_IMDB = "tt0076759"


def path_1_via_resolve() -> None:
    """Full resolve with include_variants — IMDb id will be seeded by the
    movie providers (Wikidata, TMDB, …) during normal consolidation."""
    from metadatarr.resolve import resolve

    print("=== Path 1: resolve() with include_variants ===")
    result = resolve(Signals(
        title="Star Wars",
        year=1977,
        medium=MediaType.MOVIE,
        include_variants=True,
    ))
    print(f"  accepted : {[m.provider for m in result.accepted]}")
    print(f"  imdb     : {result.external_ids.imdb}")
    releases = result.variants
    print(f"  variants : {len(releases)} found")
    for r in releases[:10]:
        ids = r.external_ids.model_dump(exclude_none=True, exclude={"extra"})
        print(f"    {r.name!r}  ids={ids}")
    if len(releases) > 10:
        print(f"    … and {len(releases) - 10} more")


def path_2_manual_list_variants() -> None:
    """Call list_variants() directly when you already have the IMDb id.

    Useful when you've resolved once, stored the IMDb id, and now just want
    to refresh the variant list without hitting every provider again.
    """
    print("\n=== Path 2: manual list_variants() with known IMDb id ===")

    known_ids = ExternalIds(imdb=KNOWN_IMDB)

    pyfanedit_provider = all_providers().get("pyfanedit")
    if pyfanedit_provider is None or not pyfanedit_provider.is_available():
        print("  pyfanedit provider unavailable — check network or fanedit.org status")
        return

    variants = pyfanedit_provider.list_variants(
        known_ids,
        signals=Signals(medium=MediaType.MOVIE),
    )
    print(f"  {len(variants)} variant(s) for IMDb {KNOWN_IMDB}")
    for v in variants[:10]:
        ids = v.external_ids.model_dump(exclude_none=True, exclude={"extra"})
        print(f"    [{v.kind.value}] {v.name!r}  ids={ids}")
    if len(variants) > 10:
        print(f"    … and {len(variants) - 10} more")


def main() -> None:
    path_1_via_resolve()
    path_2_manual_list_variants()


if __name__ == "__main__":
    main()
