"""Inspect which active providers support variant fan-out.

User story: "Before I call resolve() with include_variants=True I want to
know which providers will actually contribute variants, so I can decide
whether it's worth the extra round-trips."

Demonstrates:
- Iterating active_providers() and checking list_variants capability
- The difference between providers that override list_variants and those
  that use the default no-op
- Calling list_variants manually to preview results before a full resolve
- No extra installs required.
"""
import inspect

import metadatarr.resolve.providers  # trigger self-registration
from metadatarr.resolve.base import MetadataProvider, active_providers
from metadatarr.resolve.external_ids import ExternalIds
from metadatarr.resolve.signals import Medium, Signals


def _has_variant_support(provider: MetadataProvider) -> bool:
    """True if the provider has overridden the default list_variants()."""
    return type(provider).list_variants is not MetadataProvider.list_variants


def main() -> None:
    print("=== All registered providers and variant support ===")
    for medium_filter, label in [
        (Medium.MOVIE, "movie"),
        (Medium.MUSIC, "music"),
        (None,         "unrestricted"),
    ]:
        providers = active_providers(medium=medium_filter)
        variant_aware = [p for p in providers if _has_variant_support(p)]
        print(f"\n  medium={label!r}  active={len(providers)}  variant-aware={len(variant_aware)}")
        for p in providers:
            flag = "✓ list_variants" if _has_variant_support(p) else "  (default no-op)"
            media = sorted(m.value for m in p.media) or ["*"]
            print(f"    {p.name:<20}  media={media}  {flag}")

    print("\n=== Dry-run: which variant providers would fire for a movie? ===")
    movie_providers = [
        p for p in active_providers(medium=Medium.MOVIE)
        if _has_variant_support(p)
    ]
    if not movie_providers:
        print("  No variant-aware movie providers active.")
        return

    # Use a known IMDb id so pyfanedit can search precisely
    known_ids = ExternalIds(imdb="tt0119217")  # Good Will Hunting
    signals = Signals(title="Good Will Hunting", medium=Medium.MOVIE)

    for p in movie_providers:
        print(f"\n  {p.name}.list_variants():")
        variants = p.list_variants(known_ids, signals)
        if not variants:
            print("    (no results)")
        for v in variants[:5]:
            ids = v.external_ids.model_dump(exclude_none=True, exclude={"extra"})
            print(f"    [{v.kind.value}] {v.name!r}  ids={ids}")
        if len(variants) > 5:
            print(f"    … and {len(variants) - 5} more")


if __name__ == "__main__":
    main()
