"""Compare a resolve() call with and without include_variants.

User story: "I want to understand what include_variants actually adds.  Show
me side-by-side what the resolver returns with the flag off and on for the
same title."

Demonstrates:
- Baseline resolve: external_ids, signals, accepted providers
- With include_variants: same baseline PLUS result.relations[Role.RELEASE]
- Runtime cost: the variant fan-out is a second pass of network calls
- The baseline result is unchanged — variants are additive
"""
import time

import metadatarr.resolve.providers  # trigger self-registration
from metadatarr.resolve import resolve
from metadatarr.resolve.entities import Role
from metadatarr.resolve.signals import Medium, Signals


def _summarise(label: str, result, elapsed: float) -> None:
    print(f"\n--- {label} ({elapsed:.2f}s) ---")
    print(f"  accepted  : {[m.provider for m in result.accepted]}")
    ids = result.external_ids.model_dump(exclude_none=True, exclude={"extra"})
    print(f"  ids       : {ids}")
    releases = result.relations.get(Role.RELEASE, [])
    print(f"  variants  : {len(releases)}")
    for r in releases[:5]:
        v_ids = r.external_ids.model_dump(exclude_none=True, exclude={"extra"})
        print(f"    {r.name!r}  {v_ids}")
    if len(releases) > 5:
        print(f"    … and {len(releases) - 5} more")


def main() -> None:
    base_signals = Signals(
        title="The Thing",
        year=1982,
        medium=Medium.MOVIE,
    )

    print("=== Without include_variants ===")
    t0 = time.monotonic()
    result_base = resolve(base_signals)
    elapsed_base = time.monotonic() - t0
    _summarise("no variants", result_base, elapsed_base)

    print("\n=== With include_variants=True ===")
    t1 = time.monotonic()
    result_variants = resolve(base_signals.model_copy(update={"include_variants": True}))
    elapsed_variants = time.monotonic() - t1
    _summarise("with variants", result_variants, elapsed_variants)

    print("\n=== Baseline is unchanged ===")
    assert result_base.external_ids == result_variants.external_ids, \
        "external_ids should be identical regardless of include_variants"
    assert [m.provider for m in result_base.accepted] == \
           [m.provider for m in result_variants.accepted], \
        "accepted providers should be identical"
    print("  external_ids match  : ✓")
    print("  accepted providers  : ✓")
    print(f"  extra cost          : {(elapsed_variants - elapsed_base):.2f}s for variant fan-out")


if __name__ == "__main__":
    main()
