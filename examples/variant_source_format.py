"""Tag files by source format so 4K and 1080p rips get separate records.

User story: "I keep both a 4K Blu-ray remux and a 1080p encode of the same
film. source_format lets me give them distinct canonical fingerprints while
still resolving to the same underlying work."

Demonstrates:
- source_format flows into signal_hash → unique canonical id per format
- compare() catches a format mismatch if a provider disagrees
- Combining source_format with variant_kind for precise tagging
- No network required.
"""
from metadatarr.resolve.signals import (
    Medium,
    Signals,
    VariantKind,
    compare,
    signal_hash,
)


def main() -> None:
    uhd = Signals(
        title="Dune",
        year=2021,
        medium=Medium.MOVIE,
        variant_kind=VariantKind.THEATRICAL,
        source_format="4K",
        region="US",
    )

    hd = Signals(
        title="Dune",
        year=2021,
        medium=Medium.MOVIE,
        variant_kind=VariantKind.THEATRICAL,
        source_format="Blu-ray",
        region="US",
    )

    print("=== 4K vs Blu-ray — different fingerprints ===")
    print(f"  4K    hash : {signal_hash(uhd)}")
    print(f"  BD    hash : {signal_hash(hd)}")
    print(f"  same?      : {signal_hash(uhd) == signal_hash(hd)}")

    print("\n=== compare() catches format disagreement ===")
    conflicts = compare(uhd, hd)
    print(f"  conflicts : {[c.signal for c in conflicts]}")
    for c in conflicts:
        print(f"    {c.signal}: {c.ours!r} vs {c.theirs!r}")

    print("\n=== source_format is case-insensitive ===")
    uhd_lower = uhd.model_copy(update={"source_format": "4k"})
    print(f"  '4K' vs '4k' conflicts: {compare(uhd, uhd_lower)}")

    print("\n=== Vinyl vs CD for an album ===")
    vinyl = Signals(
        title="Dark Side of the Moon",
        artist="Pink Floyd",
        medium=Medium.MUSIC,
        source_format="Vinyl",
        variant_kind=VariantKind.REMASTERED,
        year=1973,
    )
    cd = vinyl.model_copy(update={"source_format": "CD"})
    vinyl_cd_conflicts = compare(vinyl, cd)
    print(f"  Vinyl vs CD conflicts : {[c.signal for c in vinyl_cd_conflicts]}")
    print(f"  Vinyl hash : {signal_hash(vinyl)}")
    print(f"  CD    hash : {signal_hash(cd)}")


if __name__ == "__main__":
    main()
