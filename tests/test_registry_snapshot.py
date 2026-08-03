"""Registry-snapshot equality: the module reorganizations in this change set
(pymal split, deprecation cleanup) must not add, remove, or rename any
registered provider.

The expected set below is the registry recorded before the reorganization.
Collected via a fresh subprocess import so other test modules that register
throwaway fake providers into the process-global registry (a shared,
in-process dict) can never pollute this comparison.
"""
from __future__ import annotations

import subprocess
import sys

EXPECTED_PROVIDER_NAMES = {
    "anilist",
    "annas_archive",
    "apple_podcasts",
    "audiodb",
    "bandcamp",
    "bluray_com",
    "discogs",
    "dvdcompare",
    "hanime",
    "jikan_anime",
    "jikan_manga",
    "librivox",
    "metal_archives",
    "musicbrainz",
    "openlibrary",
    "pyfanedit",
    "pymal_anime",
    "pymal_character",
    "pymal_manga",
    "pymal_person",
    "skyhook",
    "soundcloud",
    "tmdb",
    "tvdb",
    "tvmaze",
    "wikidata",
    "youtube_music",
}

_COLLECT_SNIPPET = (
    "from metadatarr.resolve import all_providers\n"
    "print(','.join(sorted(all_providers().keys())))\n"
)


def test_registry_names_unchanged_by_module_reorganization():
    result = subprocess.run(
        [sys.executable, "-c", _COLLECT_SNIPPET],
        capture_output=True, text=True, check=True,
    )
    names = set(result.stdout.strip().split(","))
    assert names == EXPECTED_PROVIDER_NAMES
