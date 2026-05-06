"""Model a film that was released differently by region.

User story: "The Japanese theatrical release of a film had an alternate ending.
I want region + variant_kind to produce a separate canonical record from the
US release, even though the title and year are identical."

Also covers:
- region vs country: country is the work's production origin (always "US" for
  a Hollywood film); region is where THIS COPY was released/purchased.
- How the resolver treats them: country comes from provider signals, region is
  set by the caller.
- No network required.
"""
from mediavocab import MediaType, VariantKind
from mediavocab.models.signals import Signals, compare_signals as compare, signal_hash


def main() -> None:
    us_theatrical = Signals(
        title="Alien",
        year=1979,
        medium=MediaType.MOVIE,
        country="US",          # production origin — set by providers
        variant_kind=VariantKind.THEATRICAL,
        region="US",           # where this copy was released
    )

    jp_theatrical = Signals(
        title="Alien",
        year=1979,
        medium=MediaType.MOVIE,
        country="US",          # same production country
        variant_kind=VariantKind.THEATRICAL,
        region="JP",           # Japanese regional release
    )

    print("=== Region distinguishes releases of the same cut ===")
    print(f"  US hash : {signal_hash(us_theatrical)}")
    print(f"  JP hash : {signal_hash(jp_theatrical)}")
    print(f"  same?   : {signal_hash(us_theatrical) == signal_hash(jp_theatrical)}")

    conflicts = compare(us_theatrical, jp_theatrical)
    print(f"\n  conflicts: {[c.signal for c in conflicts]}")
    for c in conflicts:
        print(f"    {c.signal}: {c.ours!r} vs {c.theirs!r}")
    print("  → region mismatch surfaces as a conflict; caller can decide whether to quarantine")

    print("\n=== country is NOT the same as region ===")
    # Providers typically set `country` from the work's production metadata;
    # callers set `region` to describe where they obtained this copy.
    # A JP regional release of a US film has country=US, region=JP.
    no_region = Signals(
        title="Alien",
        year=1979,
        medium=MediaType.MOVIE,
        country="US",
        variant_kind=VariantKind.THEATRICAL,
    )
    conflicts_country = compare(us_theatrical, no_region)
    print(f"  US (region set) vs no region: conflicts = {[c.signal for c in conflicts_country]}")
    print("  → region absent on one side → no conflict (caller simply hasn't declared it)")

    print("\n=== Combining region + cut for maximum precision ===")
    jp_directors = Signals(
        title="Blade Runner",
        year=1982,
        medium=MediaType.MOVIE,
        variant_kind=VariantKind.DIRECTORS,
        region="JP",
        source_format="Blu-ray",
    )
    us_directors = jp_directors.model_copy(update={"region": "US"})
    print(f"  JP Director's Cut hash : {signal_hash(jp_directors)}")
    print(f"  US Director's Cut hash : {signal_hash(us_directors)}")


if __name__ == "__main__":
    main()
