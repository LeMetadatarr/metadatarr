"""Separate standard, deluxe, and free-text editions of the same album.

User stories:
  A. "I have the standard and deluxe editions of an album. They share a title
     but must be different canonical records."
  B. "My copy has a weird pressing label not covered by VariantKind — I want
     to preserve it in edition (free-text) alongside variant_kind=OTHER."

Demonstrates:
- STANDARD vs DELUXE produces a conflict → separate records
- edition (free-text) survives unknown variant labels
- merged() picks up edition alongside variant_kind
- No network required.
"""
from metadatarr.resolve.signals import (
    Medium,
    Signals,
    VariantKind,
    compare,
    merged,
    signal_hash,
)


def story_a_standard_vs_deluxe() -> None:
    print("=== A: standard vs deluxe ===")

    standard = Signals(
        title="Midnights",
        artist="Taylor Swift",
        year=2022,
        medium=Medium.MUSIC,
        variant_kind=VariantKind.STANDARD,
    )

    deluxe = Signals(
        title="Midnights",
        artist="Taylor Swift",
        year=2022,
        medium=Medium.MUSIC,
        variant_kind=VariantKind.DELUXE,
        edition="3am Edition",
    )

    conflicts = compare(standard, deluxe)
    print(f"  conflicts : {[c.signal for c in conflicts]}")
    print(f"  standard hash : {signal_hash(standard)}")
    print(f"  deluxe   hash : {signal_hash(deluxe)}")
    print(f"  same?         : {signal_hash(standard) == signal_hash(deluxe)}")


def story_b_free_text_edition() -> None:
    print("\n=== B: free-text edition for non-enum pressing ===")

    base = Signals(
        title="Kid A",
        artist="Radiohead",
        year=2000,
        medium=Medium.MUSIC,
    )

    # A promotional double-LP pressing — no specific enum value fits
    promo = Signals(
        title="Kid A",
        artist="Radiohead",
        year=2000,
        medium=Medium.MUSIC,
        variant_kind=VariantKind.OTHER,
        edition="UK Promo Double LP",
        source_format="Vinyl",
        region="GB",
    )

    # compare: base has no variant_kind → no conflict on that field
    conflicts = compare(base, promo)
    print(f"  base vs promo conflicts : {[c.signal for c in conflicts]}")

    merged_result = merged(base, promo)
    print(f"  merged edition      : {merged_result.edition!r}")
    print(f"  merged variant_kind : {merged_result.variant_kind}")
    print(f"  merged source_format: {merged_result.source_format}")
    print(f"  promo hash          : {signal_hash(promo)}")


def main() -> None:
    story_a_standard_vs_deluxe()
    story_b_free_text_edition()


if __name__ == "__main__":
    main()
