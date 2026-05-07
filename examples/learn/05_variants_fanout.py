"""Step 5 — variant fan-out: every cut, edition, fanedit of one Work.

Set ``signals.include_variants=True`` and the resolver runs a second
pass: every provider's ``list_variants(external_ids)`` is called, and
the unique results land on ``ResolveResult.variants`` (deduped first-
seen-wins).

Use this for "show me every known release of Blade Runner" questions.
"""
from mediavocab import MediaType, Signals
from metadatarr.resolve import resolve


def main() -> None:
    sig = Signals(title="Alien", year=1979, medium=MediaType.MOVIE,
                  include_variants=True)
    result = resolve(sig)

    print(f"Anchor: {sig.title} ({sig.year})")
    print(f"  imdb       = {result.external_ids.imdb}")
    print(f"  fanedit_id = {result.external_ids.fanedit_id}")

    print(f"\nVariants ({len(result.variants)}):")
    if not result.variants:
        print("  (none returned — pyfanedit may be rate-limited)")
        return
    for v in result.variants[:15]:
        ids = v.external_ids.model_dump(exclude_none=True)
        ids.pop("extra", None)
        print(f"  • {v.name:<48} role={v.role.value:<8} ids={ids}")


if __name__ == "__main__":
    main()
