"""Cross-provider artist/album merge.

Shows how the four music providers contribute different slices of
identity to a single resolved record:

- ``musicbrainz``     → MusicBrainz IDs (artist + recording + release MBID)
- ``metal_archives``  → Encyclopaedia Metallum band/release/label IDs
- ``metadatarr``      → Lidarr's public metadata server (api.lidarr.audio,
                        wrapped by ``ArrMetadataClient``) — MusicBrainz
                        artist MBID coming back from a different angle
- ``wikidata``        → Wikidata Q-id + cross-references (IMDb, MusicBrainz)

For each test band, the script:

1. Lists which of the four providers are available in this process
   (Metal Archives needs ``pip install metadatarr[metal_archives]``);
2. Calls each provider individually so you can see the partial responses;
3. Calls ``consolidate()`` to fuse them into one ``ResolveResult`` and
   prints which fields came from which provider.

Run it with::

    python examples/resolve_artist_merge.py

You'll need a working network connection. Providers that aren't configured
self-disable and are reported as such.
"""
from __future__ import annotations

from typing import Iterable, List

from metadatarr.resolve import (
    ExternalIds,
    MediaType,
    ProviderMatch,
    ResolveResult,
    Signals,
    active_providers,
    all_providers,
    consolidate,
    enrich,
)


# Providers we want to spotlight. Order is presentation-only — confidence
# (set inside each lookup) determines who anchors the merged record.
TARGET = ("musicbrainz", "metal_archives", "skyhook", "wikidata")


# (artist, song-or-album title) — pick a mix of metal / electronic / rock so
# every provider has something to say for at least one row.
BANDS = [
    ("Iron Maiden", "The Trooper"),
    ("Mayhem",      "Freezing Moon"),
    ("Daft Punk",   "Around the World"),
    ("Pink Floyd",  "Time"),
    ("Burzum",      "Dunkelheit"),
]


# ---------------------------------------------------------------------------
# Pretty-printing helpers
# ---------------------------------------------------------------------------

def _ids_set(ext: ExternalIds) -> dict:
    return ext.model_dump(exclude_none=True)


def _diff_ids(before: ExternalIds, after: ExternalIds) -> dict:
    """Fields that landed in *after* but weren't in *before*."""
    a = _ids_set(before)
    b = _ids_set(after)
    out = {}
    for k, v in b.items():
        if a.get(k) != v:
            out[k] = v
    return out


def _print_provider_match(name: str, match: ProviderMatch | None) -> None:
    if match is None:
        print(f"  ✗  {name:<16} no match")
        return
    ids = _ids_set(match.external_ids)
    print(f"  ✓  {name:<16} confidence={match.confidence:.2f}  ids={ids}")
    relations = match.relations or {}
    if relations:
        rel_summary = ", ".join(
            f"{role.value}={[e.name for e in entries[:2]]}"
            for role, entries in relations.items()
        )
        print(f"     relations: {rel_summary}")


def _print_merge_attribution(matches: List[ProviderMatch],
                             result: ResolveResult) -> None:
    """Walk the (sorted-by-confidence) accepted matches and show which
    provider first contributed each ExternalIds field."""
    print("\n  merged identity (field → provider that contributed it):")
    seen: ExternalIds = ExternalIds()
    for match in result.accepted:
        new_keys = _diff_ids(seen, seen.merge(match.external_ids))
        for k, v in new_keys.items():
            print(f"    {k:<25} = {v}   ← {match.provider}")
        seen = seen.merge(match.external_ids)
    if not _ids_set(seen):
        print("    (no fields landed)")
    print(f"\n  conflicts dropped: {len(result.dropped)}")
    for diag in result.conflicts:
        fields = ", ".join(f"{c.signal}({c.ours}≠{c.theirs})" for c in diag.fields)
        print(f"    - {diag.provider:<16} clashed with {diag.against}: {fields}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _spotlit_providers() -> List:
    available = {p.name: p for p in active_providers(medium=MediaType.MUSIC)}
    chosen = [available[name] for name in TARGET if name in available]
    missing = [name for name in TARGET if name not in available]
    if missing:
        print("(disabled — missing config or optional dep:", ", ".join(missing) + ")")
    return chosen


def main() -> None:
    print("registered providers:",
          ", ".join(sorted(all_providers().keys())))
    providers = _spotlit_providers()
    if not providers:
        print("\nNo target provider is active right now. Install metal_archives if")
        print("you want it:  pip install metadatarr[metal_archives]")
        print("(musicbrainz, metadatarr, and wikidata are always available)")
        return

    for artist, title in BANDS:
        print("\n" + "=" * 78)
        print(f"  {artist} — {title}")
        print("=" * 78)
        signals = Signals(title=title, artist=artist, medium=MediaType.MUSIC)

        matches: List[ProviderMatch] = []
        for provider in providers:
            try:
                match = provider.lookup(signals)
            except Exception as exc:
                print(f"  !! {provider.name:<16} error: {exc}")
                continue
            _print_provider_match(provider.name, match)
            if match is not None:
                matches.append(match)

        if not matches:
            print("\n  no provider returned a match")
            continue

        result = consolidate(matches, local=signals)
        _print_merge_attribution(matches, result)

        # Round-trip enrichment: hand the consolidated IDs back to the
        # resolver so providers' ID-keyed paths can fill in cross-refs the
        # search-by-title path missed (e.g. Wikidata's claim map for an
        # MBID we just learned).
        before = result.external_ids.model_dump(exclude_none=True)
        enriched = enrich(result.external_ids, medium=MediaType.MUSIC)
        after = enriched.model_dump(exclude_none=True)
        gained = {
            k: v for k, v in after.items()
            if before.get(k) != v and k != "extra"
        }
        gained_extra = {
            k: v for k, v in (after.get("extra") or {}).items()
            if (before.get("extra") or {}).get(k) != v
        }
        if gained or gained_extra:
            print("\n  enrich() round-trip — fields added by ID-keyed lookups:")
            for k, v in gained.items():
                print(f"    {k:<25} = {v}")
            for k, v in gained_extra.items():
                print(f"    extra.{k:<19} = {v}")
        else:
            print("\n  enrich() round-trip — no additional fields surfaced")


if __name__ == "__main__":
    main()
