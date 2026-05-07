"""Step 3 — search() vs resolve(): when do you want which?

- ``search(signals)`` returns the **ranked candidate union** — every
  provider's match for a UI list, no consolidation.
- ``resolve(signals)`` returns one consolidated ``ResolveResult`` —
  the consensus answer with conflicts surfaced.

Pipeline equivalence: ``consolidate(search(s), s) == resolve(s)``.
"""
from mediavocab import MediaType, Signals
from metadatarr.resolve import resolve, search


def main() -> None:
    sig = Signals(title="Inception", year=2010, medium=MediaType.MOVIE)

    print("=== search() — ranked candidate union, no consolidation ===")
    cands = search(sig)
    for i, c in enumerate(cands[:8], 1):
        ids = c.external_ids.model_dump(exclude_none=True)
        ids.pop("extra", None)
        print(f"  {i}. {c.provider:<14} confidence={c.confidence:.2f}  ids={ids}")

    print("\n=== resolve() — one consensus, conflicts surfaced ===")
    result = resolve(sig)
    print(f"  imdb={result.external_ids.imdb}  "
          f"tmdb_movie={result.external_ids.tmdb_movie}  "
          f"wikidata={result.external_ids.wikidata}")
    print(f"  accepted={len(result.accepted)} dropped={len(result.dropped)}")
    if result.conflicts:
        print(f"  conflicts:")
        for c in result.conflicts:
            fields = ", ".join(f"{f.signal}({f.ours}≠{f.theirs})" for f in c.fields)
            print(f"    ✗ {c.provider} clashed against {c.against} on {fields}")


if __name__ == "__main__":
    main()
