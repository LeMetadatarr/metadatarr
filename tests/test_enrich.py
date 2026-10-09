"""metadatarr.resolve.enrich() — ID → more IDs, offline."""
from typing import Optional

import pytest

from metadatarr.resolve import (
    EntityRole,
    ExternalIds,
    EntityKind,
    MediaType,
    MetadataProvider,
    enrich,
)
from metadatarr.resolve._cache import cache, cached_enrich
from metadatarr.resolve.mappings import MappingEntry, get_store, reload


@pytest.fixture(autouse=True)
def _clear_cache():
    cache().clear()
    yield
    cache().clear()
    reload()  # discard any runtime mappings between tests


# ---------------------------------------------------------------------------
# Top-level fan-out semantics
# ---------------------------------------------------------------------------

class _Stub(MetadataProvider):
    name = "stub"
    media = {MediaType.MUSIC}

    def __init__(self, enrichment: Optional[ExternalIds]):
        self._enrichment = enrichment

    def is_available(self) -> bool:
        return True

    def lookup(self, signals):
        return None

    def enrich(self, external_ids):
        return self._enrichment


def test_enrich_merges_provider_results(monkeypatch):
    p = _Stub(ExternalIds(wikidata="Q1"))
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [p],
    )
    out = enrich(ExternalIds(musicbrainz_artist="m"), apply_maps=False)
    assert out.musicbrainz_artist == "m"   # input preserved
    assert out.wikidata == "Q1"            # provider added


def test_enrich_first_writer_wins(monkeypatch):
    """Provider can't overwrite a field the input already has."""
    p = _Stub(ExternalIds(wikidata="Q-from-provider"))
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [p],
    )
    out = enrich(ExternalIds(wikidata="Q-from-caller"), apply_maps=False)
    assert out.wikidata == "Q-from-caller"


def test_enrich_handles_provider_returning_none(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [_Stub(None)],
    )
    out = enrich(ExternalIds(musicbrainz_artist="m"), apply_maps=False)
    assert out.musicbrainz_artist == "m"
    assert out.wikidata is None


def test_enrich_swallows_provider_exception(monkeypatch):
    class Boom(MetadataProvider):
        name = "boom"
        media = {MediaType.MUSIC}
        def is_available(self): return True
        def lookup(self, s): return None
        def enrich(self, ids):
            raise RuntimeError("dead")
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [Boom()],
    )
    out = enrich(ExternalIds(musicbrainz_artist="m"), apply_maps=False)
    assert out.musicbrainz_artist == "m"


def test_enrich_applies_mappings_when_requested(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [],   # no providers — only the mapping should fire
    )
    # Add a runtime mapping: musicbrainz_artist=m → wikidata=Q-mapped.
    get_store().add(MappingEntry(EntityRole.ARTIST, None,
                                 {"musicbrainz_artist": "m",
                                  "wikidata": "Q-mapped"}))
    out = enrich(ExternalIds(musicbrainz_artist="m"))
    assert out.wikidata == "Q-mapped"


def test_enrich_skips_mappings_when_apply_maps_false(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [],
    )
    get_store().add(MappingEntry(EntityRole.ARTIST, None,
                                 {"musicbrainz_artist": "m",
                                  "wikidata": "Q-mapped"}))
    out = enrich(ExternalIds(musicbrainz_artist="m"), apply_maps=False)
    assert out.wikidata is None


# ---------------------------------------------------------------------------
# cached_enrich — hit / miss memoisation
# ---------------------------------------------------------------------------

class _Counted(MetadataProvider):
    name = "counted"
    media = {MediaType.MOVIE}

    def __init__(self, return_value):
        self._return = return_value
        self.calls = 0

    def is_available(self): return True
    def lookup(self, s): return None
    def enrich(self, ids):
        self.calls += 1
        return self._return


def test_cached_enrich_memoises_hit():
    p = _Counted(ExternalIds(wikidata="Q1"))
    ids = ExternalIds(musicbrainz_artist="m")
    a = cached_enrich(p, ids)
    b = cached_enrich(p, ids)
    assert a == b
    assert p.calls == 1


def test_cached_enrich_memoises_miss():
    p = _Counted(None)
    ids = ExternalIds(musicbrainz_artist="m")
    assert cached_enrich(p, ids) is None
    assert cached_enrich(p, ids) is None
    assert p.calls == 1


def test_cached_enrich_distinguishes_inputs():
    p = _Counted(ExternalIds(wikidata="Q1"))
    cached_enrich(p, ExternalIds(musicbrainz_artist="m1"))
    cached_enrich(p, ExternalIds(musicbrainz_artist="m2"))
    assert p.calls == 2


# ---------------------------------------------------------------------------
# Per-provider enrich() overrides — offline, with stubbed clients
# ---------------------------------------------------------------------------

def test_audiodb_enrich_artist_by_mbid():
    from metadatarr.resolve.providers.audiodb import AudioDBProvider

    class FakeArtist:
        id = "111"
    class FakeClient:
        def get_artist_by_mbid(self, mbid): return FakeArtist()
        def get_album_by_mbid(self, mbid): return None
        def get_track_by_mbid(self, mbid): return None

    p = AudioDBProvider()
    p._client = FakeClient()
    out = p.enrich(ExternalIds(musicbrainz_artist="abc"))
    assert out is not None
    assert out.extra["audiodb_artist_id"] == "111"


def test_audiodb_enrich_returns_none_without_keys():
    from metadatarr.resolve.providers.audiodb import AudioDBProvider
    p = AudioDBProvider()
    assert p.enrich(ExternalIds()) is None


def test_tvmaze_enrich_by_tvdb():
    from metadatarr.resolve.providers.tvmaze import TVmazeProvider

    class FakeExt:
        imdb = "tt7137906"
        thetvdb = 355567
    class FakeShow:
        id = 12345
        url = "https://tvmaze.com/shows/12345"
        externals = FakeExt()
    class FakeClient:
        def lookup_by_thetvdb(self, tvdb): return FakeShow()
        def lookup_by_imdb(self, imdb): return None

    p = TVmazeProvider()
    p._client = FakeClient()
    out = p.enrich(ExternalIds(tvdb=355567))
    assert out is not None
    assert out.imdb == "tt7137906"
    assert out.tvdb == 355567
    assert out.extra["tvmaze_id"] == "12345"


def test_tvmaze_enrich_returns_none_without_id():
    from metadatarr.resolve.providers.tvmaze import TVmazeProvider
    p = TVmazeProvider()
    assert p.enrich(ExternalIds()) is None


def test_servarr_proxy_enrich_by_isbn():
    from metadatarr.resolve.providers.servarr_proxy import ServarrProxyProvider

    class FakeEdition:
        work_keys = ["OL27482W"]
        isbn_10 = ["0261103288"]
        isbn_13 = ["9780261103283"]
    class FakeOL:
        def get_edition_by_isbn(self, isbn): return FakeEdition()
        def get_work(self, olid): return None

    p = ServarrProxyProvider()
    p._ol = FakeOL()
    out = p.enrich(ExternalIds(isbn_13="9780261103283"))
    assert out is not None
    assert out.olid == "OL27482W"


def test_servarr_proxy_enrich_returns_none_without_keys():
    from metadatarr.resolve.providers.servarr_proxy import ServarrProxyProvider
    p = ServarrProxyProvider()
    assert p.enrich(ExternalIds()) is None


# ---------------------------------------------------------------------------
# MusicBrainz — URL relations from MBID
# ---------------------------------------------------------------------------

def test_musicbrainz_enrich_walks_url_relations(monkeypatch):
    from metadatarr.resolve.providers.musicbrainz import MusicBrainzProvider

    payload = {
        "relations": [
            {"target-type": "url", "type": "wikidata",
             "url": {"resource": "https://www.wikidata.org/wiki/Q12345"}},
            {"target-type": "url", "type": "bandcamp",
             "url": {"resource": "https://acme.bandcamp.com/"}},
            {"target-type": "url", "type": "soundcloud",
             "url": {"resource": "https://soundcloud.com/acme"}},
            {"target-type": "url", "type": "discogs",
             "url": {"resource": "https://www.discogs.com/artist/9999"}},
            {"target-type": "url", "type": "imdb",
             "url": {"resource": "https://www.imdb.com/name/nm1234567/"}},
            {"target-type": "url", "type": "youtube",
             "url": {"resource": "https://youtube.com/@acme"}},
            # Non-URL relation; ignored.
            {"target-type": "artist", "type": "member of",
             "artist": {"id": "abc"}},
        ],
    }

    class _Resp:
        def __init__(self, p): self._p = p
        def raise_for_status(self): pass
        def json(self): return self._p

    monkeypatch.setattr(
        "metadatarr.resolve.providers.musicbrainz._SESSION.get",
        lambda *a, **kw: _Resp(payload),
    )
    p = MusicBrainzProvider()
    out = p.enrich(ExternalIds(musicbrainz_artist="abc-mbid"))
    assert out is not None
    assert out.wikidata == "Q12345"
    assert out.imdb == "nm1234567"
    assert out.extra.get("bandcamp_artist_url") == "https://acme.bandcamp.com/"
    assert out.extra.get("soundcloud_artist_url") == "https://soundcloud.com/acme"
    assert out.extra.get("discogs_url") == "https://www.discogs.com/artist/9999"
    assert out.extra.get("youtube_channel_url") == "https://youtube.com/@acme"


def test_musicbrainz_enrich_returns_none_without_mbid():
    from metadatarr.resolve.providers.musicbrainz import MusicBrainzProvider
    p = MusicBrainzProvider()
    assert p.enrich(ExternalIds()) is None


# ---------------------------------------------------------------------------
# Metal Archives — band external links
# ---------------------------------------------------------------------------

def test_metal_archives_enrich_band_links():
    from metadatarr.resolve.providers.metal_archives import MetalArchivesProvider

    class FakeLink:
        def __init__(self, name, url):
            self.name = name
            self.url = url

    class FakeClient:
        def get_links(self, entity_id, entity_type="band"):
            assert entity_type == "band"
            assert entity_id == 25
            return [
                FakeLink("Bandcamp",  "https://ironmaiden.bandcamp.com/"),
                FakeLink("Wikipedia", "https://en.wikipedia.org/wiki/Iron_Maiden"),
                FakeLink("Wikidata",  "https://www.wikidata.org/wiki/Q35535"),
                FakeLink("Discogs",   "https://www.discogs.com/artist/251595"),
            ]

    p = MetalArchivesProvider()
    p._available = True
    p._client = FakeClient()
    out = p.enrich(ExternalIds(metal_archives_band=25))
    assert out is not None
    assert out.wikidata == "Q35535"
    assert out.extra.get("bandcamp_artist_url") == "https://ironmaiden.bandcamp.com/"
    assert out.extra.get("wikipedia_url").startswith("https://en.wikipedia.org/")
    assert out.extra.get("discogs_url").startswith("https://www.discogs.com/")


def test_metal_archives_enrich_returns_none_without_keys():
    from metadatarr.resolve.providers.metal_archives import MetalArchivesProvider
    p = MetalArchivesProvider()
    p._available = True
    p._client = object()
    assert p.enrich(ExternalIds()) is None


# ---------------------------------------------------------------------------
# Bandcamp — Track URL → numeric ids via py_bandcamp.BandcampTrack.from_url
# ---------------------------------------------------------------------------

def test_bandcamp_enrich_track_via_from_url(monkeypatch):
    from metadatarr.resolve.providers.bandcamp import BandcampProvider

    class FakeTrack:
        track_id = 4148437766
        band_id = 2099893691
        album_id = None

    monkeypatch.setattr(
        "py_bandcamp.BandcampTrack.from_url",
        staticmethod(lambda url: FakeTrack()),
    )
    p = BandcampProvider()
    p._available = True
    out = p.enrich(ExternalIds(extra={
        "bandcamp_track_url": "https://acme.bandcamp.com/track/foo",
    }))
    assert out is not None
    assert out.extra["bandcamp_track_id"] == "4148437766"
    assert out.extra["bandcamp_band_id"] == "2099893691"


def test_bandcamp_enrich_returns_none_without_url():
    from metadatarr.resolve.providers.bandcamp import BandcampProvider
    p = BandcampProvider()
    p._available = True
    assert p.enrich(ExternalIds()) is None


# ---------------------------------------------------------------------------
# SoundCloud — URL → numeric ids via nuvem_de_som
# ---------------------------------------------------------------------------

def test_soundcloud_enrich_track_url():
    from metadatarr.resolve.providers.soundcloud import SoundCloudProvider

    class FakeClient:
        def resolve_user(self, url): return None
        def resolve_track(self, url):
            return {"track_id": 178995436, "user_id": 44345,
                    "title": "x", "url": url}

    p = SoundCloudProvider()
    p._available = True
    p._client = FakeClient()
    out = p.enrich(ExternalIds(extra={
        "soundcloud_track_url": "https://soundcloud.com/acme/foo",
    }))
    assert out is not None
    assert out.extra["soundcloud_track_id"] == "178995436"
    assert out.extra["soundcloud_user_id"] == "44345"


def test_soundcloud_enrich_artist_url():
    from metadatarr.resolve.providers.soundcloud import SoundCloudProvider

    class FakeClient:
        def resolve_user(self, url):
            return {"artist": "Acme", "artist_url": url, "image": "",
                    "user_id": 44345}
        def resolve_track(self, url): return None

    p = SoundCloudProvider()
    p._available = True
    p._client = FakeClient()
    out = p.enrich(ExternalIds(extra={
        "soundcloud_artist_url": "https://soundcloud.com/acme",
    }))
    assert out is not None
    assert out.extra["soundcloud_user_id"] == "44345"


def test_soundcloud_enrich_handles_old_nuvem_no_resolve_track():
    """When the installed nuvem_de_som predates resolve_track(), we fall
    through gracefully — no AttributeError surfaced to the caller."""
    from metadatarr.resolve.providers.soundcloud import SoundCloudProvider

    class OldClient:
        def resolve_user(self, url): return None
        # no resolve_track method

    p = SoundCloudProvider()
    p._available = True
    p._client = OldClient()
    out = p.enrich(ExternalIds(extra={
        "soundcloud_track_url": "https://soundcloud.com/x/y",
    }))
    assert out is None  # nothing to merge, but no exception


def test_soundcloud_enrich_returns_none_without_keys():
    from metadatarr.resolve.providers.soundcloud import SoundCloudProvider
    p = SoundCloudProvider()
    p._available = True
    assert p.enrich(ExternalIds()) is None
