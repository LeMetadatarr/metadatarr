"""TOML-driven entity-mapping tests.

The package ships ``metadatarr/metadatarr/data/mappings.toml`` with curated
cross-platform identity assertions. These tests load that file directly
(no monkey-patching of the global store) and prove that:

1. The TOML parses cleanly into ``MappingEntry`` instances.
2. The store's reverse index is populated from those entries.
3. URL-keyed lookups work in both directions for the same entity, so an
   ``ExternalIds`` carrying just the SoundCloud URL gets enriched with the
   Bandcamp URL (and vice versa) — proving the "two providers each see
   only one platform, but the consolidated record links both" contract.
"""
from __future__ import annotations

from metadatarr.resolve.entities import EntityRole
from mediavocab.models import ExternalIds
from metadatarr.resolve.mappings import (
    MappingStore,
    _load_file,
    _package_mappings_path,
)


def _store_from_package() -> MappingStore:
    """Build a fresh, hermetic store from the shipped TOML file."""
    path = _package_mappings_path()
    assert path is not None, "package mappings.toml must be discoverable"
    store = MappingStore()
    for entry in _load_file(path):
        store.add(entry)
    return store


# ---------------------------------------------------------------------------
# 1. The Acidkid ↔ Piratech assertion is shipped + loaded.
# ---------------------------------------------------------------------------

ACIDKID_SC_URL = "https://soundcloud.com/acidkid"
PIRATECH_BC_URL = "https://piratech.bandcamp.com/"


def test_package_mappings_file_loads_at_least_one_entry():
    store = _store_from_package()
    assert len(store) >= 1


def test_acidkid_piratech_pair_is_in_the_shipped_file():
    """Both URLs must resolve to the same entry — the contract this test
    pins down is `same artist, two platforms`, not just the URLs existing."""
    store = _store_from_package()
    via_soundcloud = store.lookup(EntityRole.ARTIST,
                                  {"soundcloud_artist_url": ACIDKID_SC_URL})
    via_bandcamp = store.lookup(EntityRole.ARTIST,
                                {"bandcamp_artist_url": PIRATECH_BC_URL})
    assert via_soundcloud is not None, "soundcloud URL did not match any entry"
    assert via_bandcamp is not None, "bandcamp URL did not match any entry"
    assert via_soundcloud is via_bandcamp, \
        "the two URLs must point to the same MappingEntry instance"


# ---------------------------------------------------------------------------
# 2. apply() back-fills the missing platform's URL on either side.
# ---------------------------------------------------------------------------

def test_apply_enriches_soundcloud_with_bandcamp():
    """A bandcamp-only result should pick up the soundcloud URL from the
    mapping (and vice versa)."""
    store = _store_from_package()

    # Provider knows only the bandcamp side
    only_bc = ExternalIds(extra={"bandcamp_artist_url": PIRATECH_BC_URL})
    enriched = store.apply(EntityRole.ARTIST, only_bc)
    assert enriched.extra.get("soundcloud_artist_url") == ACIDKID_SC_URL


def test_apply_enriches_bandcamp_with_soundcloud():
    store = _store_from_package()

    only_sc = ExternalIds(extra={"soundcloud_artist_url": ACIDKID_SC_URL})
    enriched = store.apply(EntityRole.ARTIST, only_sc)
    # The store normalises URLs at load time (trailing slash stripped) — the
    # back-fill carries the canonical form, not the original `…com/`.
    assert enriched.extra.get("bandcamp_artist_url") == PIRATECH_BC_URL.rstrip("/")


# ---------------------------------------------------------------------------
# 3. URL normalisation — trailing slash, scheme casing, whitespace.
# ---------------------------------------------------------------------------

def test_url_normalisation_matches_trailing_slash_variants():
    store = _store_from_package()
    # The shipped entry has bandcamp URL with a trailing slash; user data
    # often arrives without one. Both forms must resolve to the same entry.
    no_slash = store.lookup(EntityRole.ARTIST,
                            {"bandcamp_artist_url": "https://piratech.bandcamp.com"})
    with_slash = store.lookup(EntityRole.ARTIST,
                              {"bandcamp_artist_url": "https://piratech.bandcamp.com/"})
    assert no_slash is not None and with_slash is not None
    assert no_slash is with_slash


def test_url_normalisation_lowercases_host():
    store = _store_from_package()
    # Mixed-case host is a common copy-paste hazard.
    hit = store.lookup(EntityRole.ARTIST,
                       {"bandcamp_artist_url": "https://PIRATECH.bandcamp.com/"})
    assert hit is not None


# ---------------------------------------------------------------------------
# 4. Mismatched-kind lookups must NOT cross-match.
# ---------------------------------------------------------------------------

def test_kind_filtering_is_strict():
    """A URL that's filed under [[artist]] must not surface for [[album]]."""
    store = _store_from_package()
    assert store.lookup(EntityRole.ALBUM,
                        {"bandcamp_artist_url": PIRATECH_BC_URL}) is None
