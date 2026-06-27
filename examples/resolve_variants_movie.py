"""Fan out a movie resolve and collect all known release variants.

User story: "I have a file tagged as 'Apocalypse Now'. Give me the canonical
record AND a list of every known variant/fanedit so I can pick which version
I actually own."

pyfanedit searches fanedit.org (IFDB) by IMDb id (preferred) then by title.
The pyfanedit provider is variant-only — it does not participate in normal
resolution, so it never pollutes the consolidated record.
"""
import metadatarr.resolve.providers  # trigger provider self-registration
from metadatarr.resolve import resolve
from mediavocab import MediaType
from mediavocab.models.signals import Signals


def main() -> None:
    signals = Signals(
        title="Apocalypse Now",
        year=1979,
        medium=MediaType.MOVIE,
        include_variants=True,   # <-- enable variant fan-out
    )

    print("--- resolve (with variant fan-out) ---")
    result = resolve(signals)

    print(f"  accepted providers : {[m.provider for m in result.accepted]}")
    ids = result.external_ids.model_dump(exclude_none=True, exclude={"extra"})
    print(f"  external_ids       : {ids}")
    if result.external_ids.extra:
        print(f"  extra              : {result.external_ids.extra}")

    releases = result.variants
    print(f"\n--- release variants ({len(releases)} found) ---")
    if not releases:
        print("  none (no network, or no fanedits indexed on IFDB for this title)")
        return
    for r in releases:
        ids_v = r.external_ids.model_dump(exclude_none=True, exclude={"extra"})
        print(f"  [{r.kind.value}] {r.name!r}  ids={ids_v}")


if __name__ == "__main__":
    main()
