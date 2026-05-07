"""Step 1 — your first cross-source lookup.

The shortest useful program: ask the resolver for a movie and print
what it found. Every built-in provider is keyless and self-registers
on import; you don't need to configure anything.
"""
from mediavocab import MediaType, Signals
from metadatarr.resolve import resolve


def main() -> None:
    result = resolve(Signals(title="Inception", year=2010,
                             medium=MediaType.MOVIE))
    print(f"resolved: {result.signals.title} ({result.signals.year})")
    print(f"  imdb       = {result.external_ids.imdb}")
    print(f"  tmdb_movie = {result.external_ids.tmdb_movie}")
    print(f"  wikidata   = {result.external_ids.wikidata}")
    print(f"\n  accepted from {len(result.accepted)} providers:")
    for m in result.accepted:
        print(f"    ✓ {m.provider:<14} confidence={m.confidence:.2f}")


if __name__ == "__main__":
    main()
