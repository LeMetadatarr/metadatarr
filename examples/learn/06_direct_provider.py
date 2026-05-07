"""Step 6 — calling a single provider directly.

You don't always want the consolidator. To inspect what one provider
says, look it up in the registry and call ``.lookup(signals)`` yourself.
This is how you build "compare what each source thinks" UIs.
"""
from mediavocab import MediaType, Signals
from metadatarr.resolve import all_providers


def main() -> None:
    sig = Signals(title="OK Computer", artist="Radiohead",
                  medium=MediaType.MUSIC)

    print(f"Query: {sig.title} — {sig.artist}\n")
    print(f"{'Provider':<18} confidence  ids")
    print("-" * 78)
    for name, provider in all_providers().items():
        if not provider.is_available():
            continue
        if not provider.matches(sig):
            continue
        try:
            match = provider.lookup(sig)
        except Exception as exc:
            print(f"{name:<18}  ERR  {type(exc).__name__}: {exc}")
            continue
        if match is None:
            print(f"{name:<18}   —    (no result)")
            continue
        ids = match.external_ids.model_dump(exclude_none=True)
        ids.pop("extra", None)
        # Keep the line short
        ids_short = {k: v for k, v in ids.items()
                     if k.startswith("musicbrainz") or k in ("wikidata",)}
        print(f"{name:<18}  {match.confidence:.2f}   {ids_short}")


if __name__ == "__main__":
    main()
