"""End-to-end resolver walkthrough.

Shows how to fan a noisy local row out to every active movie provider and
consolidate their answers into a single canonical record.
"""
from metadatarr.resolve import (
    MediaType,
    Signals,
    active_providers,
    consolidate,
    resolve,
)


def main() -> None:
    local = Signals(title="Inception", year=2010, medium=MediaType.MOVIE)

    print("--- active movie providers ---")
    providers = active_providers(medium=MediaType.MOVIE)
    for p in providers:
        print(f"  {p.name}  media={sorted(m.value for m in p.media) or '*'}")

    print("\n--- per-provider matches ---")
    matches = []
    for provider in providers:
        match = provider.lookup(local)
        if match is None:
            print(f"  {provider.name}: no match")
            continue
        matches.append(match)
        print(f"  {provider.name}: confidence={match.confidence:.2f}  ids={match.external_ids.model_dump(exclude_none=True)}")

    print("\n--- consolidate() ---")
    result = consolidate(matches, local=local)
    print(f"  accepted: {[m.provider for m in result.accepted]}")
    print(f"  dropped:  {[m.provider for m in result.dropped]}")
    print(f"  external_ids: {result.external_ids.model_dump(exclude_none=True)}")
    print(f"  signals: {result.signals}")

    print("\n--- resolve() one-shot ---")
    one_shot = resolve(local)
    print(f"  external_ids: {one_shot.external_ids.model_dump(exclude_none=True)}")


if __name__ == "__main__":
    main()
