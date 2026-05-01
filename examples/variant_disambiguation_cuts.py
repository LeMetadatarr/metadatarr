"""Resolve the same film title to two distinct canonical records by cut.

User story: "I have two files both named 'The Lord of the Rings: The Two
Towers'. One is the theatrical cut, the other is the Extended Edition. I need
separate canonical records with different hashes so my library doesn't
collapse them into one entry."

Demonstrates:
- variant_kind keeps two otherwise-identical Signals bags distinct
- signal_hash produces different fingerprints for each cut
- compare() flags the conflict if a provider returns the wrong cut
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
    theatrical = Signals(
        title="The Lord of the Rings: The Two Towers",
        year=2002,
        medium=Medium.MOVIE,
        variant_kind=VariantKind.THEATRICAL,
        runtime=10920.0,   # 182 min
    )

    extended = Signals(
        title="The Lord of the Rings: The Two Towers",
        year=2002,
        medium=Medium.MOVIE,
        variant_kind=VariantKind.EXTENDED,
        runtime=13800.0,   # 223 min
    )

    print("=== Two cuts, two hashes ===")
    print(f"  theatrical hash : {signal_hash(theatrical)}")
    print(f"  extended   hash : {signal_hash(extended)}")
    print(f"  same hash?      : {signal_hash(theatrical) == signal_hash(extended)}")

    print("\n=== Cross-compare (theatrical local vs extended provider result) ===")
    conflicts = compare(theatrical, extended)
    print(f"  conflicts : {[c.signal for c in conflicts]}")
    for c in conflicts:
        print(f"    {c.signal}: {c.ours!r} vs {c.theirs!r}")
    print("  → provider result would be dropped (wrong cut)")

    print("\n=== Absent variant is not a conflict ===")
    no_variant = Signals(
        title="The Lord of the Rings: The Two Towers",
        year=2002,
        medium=Medium.MOVIE,
    )
    conflicts_none = compare(theatrical, no_variant)
    print(f"  conflicts when provider doesn't set variant_kind: {conflicts_none}")
    print("  → provider result accepted (absence = no disagreement)")


if __name__ == "__main__":
    main()
