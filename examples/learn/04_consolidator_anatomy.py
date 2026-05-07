"""Step 4 — anatomy of a ResolveResult: accepted, dropped, conflicts.

The consolidator processes provider matches highest-confidence-first.
A match disagreeing with the **local** signals (your query) goes to
``dropped`` immediately. A match disagreeing with the *previously
accepted* anchor goes to ``conflicts`` (and ``signals=None`` is
surfaced if two anchored matches irreconcilably clash).

Inspecting these three lists is how you debug "why did the resolver
land on that answer?" without re-running anything.
"""
from mediavocab import MediaType, Signals
from metadatarr.resolve import resolve


def main() -> None:
    # Pick a deliberately ambiguous query — short title that hits multiple
    # works across providers.
    sig = Signals(title="Alien", year=1979, medium=MediaType.MOVIE)
    result = resolve(sig)

    print(f"Query: {sig.title} ({sig.year})")
    print(f"\nConsensus signals:")
    if result.signals is None:
        print("  (None — irreconcilable anchor conflict)")
    else:
        for k, v in result.signals.model_dump(exclude_none=True).items():
            if v in ("", [], False):
                continue
            print(f"  {k} = {v}")

    print(f"\nMerged external IDs:")
    for k, v in result.external_ids.model_dump(exclude_none=True).items():
        if v in ("", {}, [], None):
            continue
        print(f"  {k} = {v}")

    print(f"\nAccepted ({len(result.accepted)}):")
    for m in result.accepted:
        print(f"  ✓ {m.provider:<14} confidence={m.confidence:.2f}")

    print(f"\nDropped vs local ({len(result.dropped)}):")
    for m in result.dropped:
        print(f"  ✗ {m.provider:<14} confidence={m.confidence:.2f}")

    print(f"\nConflicts ({len(result.conflicts)}):")
    for c in result.conflicts:
        fields = ", ".join(f"{f.signal}: {f.ours!r} ≠ {f.theirs!r}" for f in c.fields)
        print(f"  ✗ {c.provider:<14} vs {c.against:<14} {fields}")


if __name__ == "__main__":
    main()
