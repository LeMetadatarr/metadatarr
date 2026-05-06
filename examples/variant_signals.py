"""Demonstrate VariantKind signals and how compare() treats them.

User stories:
  A. "I know my file is the Director's Cut — only match providers that agree."
  B. "I know my pressing is the Japanese bonus-tracks edition — tag it and
     ensure a US standard release won't be treated as the same thing."
  C. "Show me what fields trigger a conflict so I can understand why a
     provider was dropped."

No network requests are made — this is a pure signal-layer demo.
"""
from mediavocab import MediaType, VariantKind
from mediavocab.models.signals import Signals, compare_signals as compare, merge_signals as merged, signal_hash


def story_a_directors_cut() -> None:
    print("=== A: Director's Cut — only accept matching provider signals ===")

    local = Signals(
        title="Blade Runner",
        year=1982,
        medium=MediaType.MOVIE,
        variant_kind=VariantKind.DIRECTORS,
    )

    theatrical = Signals(
        title="Blade Runner",
        year=1982,
        medium=MediaType.MOVIE,
        variant_kind=VariantKind.THEATRICAL,
    )

    directors = Signals(
        title="Blade Runner",
        year=1982,
        medium=MediaType.MOVIE,
        variant_kind=VariantKind.DIRECTORS,
    )

    no_variant = Signals(title="Blade Runner", year=1982, medium=MediaType.MOVIE)

    conflicts_theatrical = compare(local, theatrical)
    conflicts_directors  = compare(local, directors)
    conflicts_none       = compare(local, no_variant)

    print(f"  vs theatrical  : {len(conflicts_theatrical)} conflict(s) → {conflicts_theatrical}")
    print(f"  vs directors   : {len(conflicts_directors)} conflict(s) — accepted")
    print(f"  vs no variant  : {len(conflicts_none)} conflict(s) — accepted (absent = no disagreement)")


def story_b_regional_pressing() -> None:
    print("\n=== B: Japanese bonus-tracks edition vs US standard ===")

    # The Japanese edition adds bonus tracks; mediavocab spec §4.2 excludes
    # BONUS_TRACKS from VariantKind, so we use DELUXE (the closest first-class
    # value) plus an `edition` note describing the specifics.
    jp_edition = Signals(
        title="OK Computer",
        artist="Radiohead",
        medium=MediaType.MUSIC,
        variant_kind=VariantKind.DELUXE,
        region="JP",
        edition="Japanese edition (bonus tracks)",
        source_format="CD",
    )

    # Canonical edition: variant_kind=None per axiom 3.
    us_standard = Signals(
        title="OK Computer",
        artist="Radiohead",
        medium=MediaType.MUSIC,
        variant_kind=None,
        region="US",
        source_format="CD",
    )

    conflicts = compare(jp_edition, us_standard)
    print(f"  conflicts: {[c.signal for c in conflicts]}")
    for c in conflicts:
        print(f"    {c.signal}: {c.ours!r} vs {c.theirs!r}")

    print(f"\n  JP hash : {signal_hash(jp_edition)}")
    print(f"  US hash : {signal_hash(us_standard)}")
    print("  (different hashes → separate canonical records)")


def story_c_merge() -> None:
    print("\n=== C: merged() preserves variant signals ===")

    base = Signals(title="The Thing", year=1982, medium=MediaType.MOVIE)
    detail = Signals(
        variant_kind=VariantKind.REMASTERED,
        source_format="4K",
        region="US",
        include_variants=True,
    )

    result = merged(base, detail)
    print(f"  title          : {result.title}")
    print(f"  variant_kind   : {result.variant_kind}")
    print(f"  source_format  : {result.source_format}")
    print(f"  region         : {result.region}")
    print(f"  include_variants: {result.include_variants}")


def main() -> None:
    story_a_directors_cut()
    story_b_regional_pressing()
    story_c_merge()


if __name__ == "__main__":
    main()
