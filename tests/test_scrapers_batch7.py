"""Row-schema equivalence tests for the batch-7 Tidal scrapers.

Locks the exact flat-row shape each scraper emits against a realistic
upstream (OpenGraph HTML) sample, so a future engine change can't silently
alter the output schema.
"""
from __future__ import annotations

from metadatarr.scrapers.engine import all_sources
from metadatarr.scrapers.tidal_albums import TidalAlbumsSource
from metadatarr.scrapers.tidal_artists import TidalArtistsSource
from metadatarr.scrapers.tidal_tracks import TidalTracksSource

_ALBUM_HTML = """
<html><head>
<meta property="og:title" content="Discovery" />
<meta property="og:description" content="Album by Daft Punk &amp; Friends" />
<meta property="og:image" content="https://resources.tidal.com/images/album.jpg" />
</head></html>
"""

_TRACK_HTML = """
<html><head>
<meta property="og:title" content="One More Time" />
<meta property="og:description" content="Song by Daft Punk" />
<meta property="og:image" content="https://resources.tidal.com/images/track.jpg" />
</head></html>
"""

_ARTIST_HTML = """
<html><head>
<meta property="og:title" content="Daft Punk" />
<meta property="og:description" content="Listen to Daft Punk on TIDAL" />
<meta property="og:image" content="https://resources.tidal.com/images/artist.jpg" />
</head></html>
"""

_GENERIC_HTML = """
<html><head>
<meta property="og:title" content="TIDAL" />
</head></html>
"""


class _FakeResp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class _FakeSession:
    def __init__(self, html_by_id):
        self._html_by_id = html_by_id

    def get(self, url, timeout=None, allow_redirects=None):
        for tidal_id, html in self._html_by_id.items():
            if url.endswith(f"/{tidal_id}"):
                return _FakeResp(html)
        return _FakeResp(_GENERIC_HTML)


def test_tidal_albums_map_row_schema():
    src = TidalAlbumsSource()
    src._session = _FakeSession({1: _ALBUM_HTML, 2: _GENERIC_HTML})
    src.throttle.wait = lambda: None

    row = src._fetch_album(1)
    assert row == {
        "tidal_id": 1,
        "title": "Discovery",
        "artist": "Daft Punk & Friends",
        "description": "Album by Daft Punk & Friends",
        "image_url": "https://resources.tidal.com/images/album.jpg",
        "url": "https://tidal.com/album/1",
    }
    assert set(row) == {"tidal_id", "title", "artist", "description",
                        "image_url", "url"}

    # generic/unmapped page is skipped
    assert src._fetch_album(2) is None


def test_tidal_tracks_map_row_schema():
    src = TidalTracksSource()
    src._session = _FakeSession({1: _TRACK_HTML, 2: _GENERIC_HTML})
    src.throttle.wait = lambda: None

    row = src._fetch_track(1)
    assert row == {
        "tidal_id": 1,
        "title": "One More Time",
        "artist": "Daft Punk",
        "description": "Song by Daft Punk",
        "image_url": "https://resources.tidal.com/images/track.jpg",
        "url": "https://tidal.com/track/1",
    }
    assert set(row) == {"tidal_id", "title", "artist", "description",
                        "image_url", "url"}

    assert src._fetch_track(2) is None


def test_tidal_artists_map_row_schema():
    src = TidalArtistsSource()
    src._session = _FakeSession({1: _ARTIST_HTML, 2: _GENERIC_HTML})
    src.throttle.wait = lambda: None

    row = src._fetch_artist(1)
    assert row == {
        "tidal_id": 1,
        "name": "Daft Punk",
        "description": "Listen to Daft Punk on TIDAL",
        "image_url": "https://resources.tidal.com/images/artist.jpg",
        "url": "https://tidal.com/artist/1",
    }
    assert set(row) == {"tidal_id", "name", "description", "image_url", "url"}

    assert src._fetch_artist(2) is None


def test_tidal_scrapers_registered():
    reg = all_sources()
    assert reg.get("tidal_albums") is TidalAlbumsSource
    assert reg.get("tidal_tracks") is TidalTracksSource
    assert reg.get("tidal_artists") is TidalArtistsSource
