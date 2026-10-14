"""Expand a MusicBrainz release-group into its individual regional releases.

User story: "I have a rip tagged as 'OK Computer'. I want to see all the
official regional pressings (JP bonus tracks, US, EU, …) so I can confirm
which exact release my files came from."

MusicBrainz's ``list_variants`` implementation hits
``/ws/2/release-group/{mbrgid}/releases`` and returns one RELEASE entity per
row. Each entity carries a ``musicbrainz_release`` MBID that you can then use
for more detailed lookups (track list, label, catalogue number, …).

No extra installs required — MusicBrainz is always available.
"""
import metadatarr.resolve.providers  # trigger provider self-registration
from metadatarr.resolve import resolve
from mediavocab import MediaType
from mediavocab.models.signals import Signals


def main() -> None:
    signals = Signals(
        title="OK Computer",
        artist="Radiohead",
        year=1997,
        medium=MediaType.MUSIC,
        include_variants=True,   # <-- expand release-group → releases
    )

    print("--- resolve (with variant fan-out) ---")
    result = resolve(signals)

    print(f"  accepted providers     : {[m.provider for m in result.accepted]}")
    print(f"  musicbrainz_release_group: {result.external_ids.musicbrainz_release_group}")
    print(f"  musicbrainz_release      : {result.external_ids.musicbrainz_release}")

    releases = result.variants
    print(f"\n--- regional releases ({len(releases)} found) ---")
    if not releases:
        print("  none (MusicBrainz may not have returned a release-group MBID)")
        return
    for r in releases:
        mbid = r.external_ids.musicbrainz_release
        print(f"  {r.name!r:<40}  mbid={mbid}")


if __name__ == "__main__":
    main()
