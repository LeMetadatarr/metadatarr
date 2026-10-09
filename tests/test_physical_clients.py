"""Tests for blu-ray.com, DVDCompare, and Discogs clients.

All HTTP is intercepted — fixtures are real responses captured from live sites.
Fixture files live in tests/fixtures/physical/ and are committed to the repo.

Captured on 2026-04-30:
  bluray_com_moon_17549.html          — Moon (2009) AU Blu-ray page
  bluray_com_eden_lake_21174.html     — Eden Lake (2008) FR Blu-ray page
  dvdcompare_alien_bluray_fid16880.html — Alien Blu-ray, all regional releases
  dvdcompare_aliens_bluray_fid16881.html — Aliens Blu-ray, all regional releases
  dvdcompare_search_alien.html        — search results for "Alien"
  discogs_release_1383918.json        — Ministry LaserDisc full release
  discogs_search_alien_laserdisc.json — search: Alien, Laserdisc, Non-Music
  discogs_master_292715.json          — master release for above
  discogs_master_292715_versions.json — version list for master 292715
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from metadatarr.client import BlurayComClient, DiscogsClient, DVDCompareClient
from metadatarr.models import (
    BlurayComAudioTrack,
    BlurayComEdition,
    DiscogsCommunity,
    DiscogsFormatDetail,
    DiscogsIdentifier,
    DiscogsRelease,
    DiscogsSearchHit,
    DVDCompareEdition,
    DVDCompareRelease,
)

FIXTURES = Path(__file__).parent / "fixtures" / "physical"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _soup(name: str) -> BeautifulSoup:
    return BeautifulSoup(_html(name), "html.parser")


class _Resp:
    """Minimal fake HTTP response."""

    def __init__(self, text: str = "", data: Any = None, status: int = 200, url: str = "https://example.com/"):
        self._data = data
        self.text = text
        self.status_code = status
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._data


# ===========================================================================
# blu-ray.com
# ===========================================================================


class TestBlurayComParser:
    """Parse real fixture HTML directly — no network."""

    @pytest.fixture()
    def moon(self) -> BlurayComEdition:
        client = BlurayComClient()
        soup = _soup("bluray_com_moon_17549.html")
        return client._parse_edition_page(soup, 17549,
                                          "https://www.blu-ray.com/movies/Moon-Blu-ray/17549/")

    @pytest.fixture()
    def eden_lake(self) -> BlurayComEdition:
        client = BlurayComClient()
        soup = _soup("bluray_com_eden_lake_21174.html")
        return client._parse_edition_page(soup, 21174,
                                          "https://www.blu-ray.com/movies/Eden-Lake-Blu-ray/21174/")

    # -- identity --

    def test_title(self, moon):
        assert "Moon" in moon.title

    def test_year(self, moon):
        assert moon.year == 2010

    def test_bluray_com_id(self, moon):
        assert moon.bluray_com_id == 17549

    def test_url(self, moon):
        assert moon.url and "blu-ray.com" in moon.url

    def test_release_date(self, moon):
        assert moon.release_date == "February 24, 2010"

    # -- video --

    def test_video_codec(self, moon):
        assert moon.video_codec == "MPEG-4 AVC"

    def test_video_bitrate(self, moon):
        assert moon.video_bitrate_kbps == 24670

    def test_resolution(self, moon):
        assert moon.resolution == "1080p"

    def test_aspect_ratio(self, moon):
        assert moon.aspect_ratio == "2.40:1"

    def test_original_aspect_ratio(self, moon):
        assert moon.original_aspect_ratio == "2.39:1"

    def test_hdr_none_on_sdr_disc(self, moon):
        # Moon (2009) BD is SDR; HDR field should be absent
        assert moon.hdr is None

    # -- disc --

    def test_region_free(self, moon):
        assert moon.region and moon.region.lower() == "free"

    def test_region_b(self, eden_lake):
        assert eden_lake.region and eden_lake.region.upper() == "B"

    def test_disc_type(self, moon):
        assert moon.disc_type == "BD-50"

    def test_disc_type_bd25(self, eden_lake):
        assert eden_lake.disc_type == "BD-25"

    def test_disc_count(self, moon):
        assert moon.disc_count == 1

    def test_bd_live(self, moon):
        assert moon.bd_live is True

    # -- audio --

    def test_audio_track_count(self, moon):
        assert len(moon.audio_tracks) >= 2

    def test_english_audio_codec(self, moon):
        eng = next(t for t in moon.audio_tracks if t.language == "English")
        assert "DTS" in eng.codec

    def test_english_audio_channels(self, moon):
        eng = next(t for t in moon.audio_tracks if t.language == "English")
        assert eng.channels == "5.1"

    def test_english_audio_sample_rate(self, moon):
        eng = next(t for t in moon.audio_tracks if t.language == "English")
        assert eng.sample_rate_khz == 48.0

    def test_english_audio_bit_depth(self, moon):
        eng = next(t for t in moon.audio_tracks if t.language == "English")
        assert eng.bit_depth == 24

    def test_audio_not_descriptive_by_default(self, moon):
        assert all(not t.is_descriptive for t in moon.audio_tracks)

    def test_eden_lake_dual_audio(self, eden_lake):
        langs = {t.language for t in eden_lake.audio_tracks}
        assert "English" in langs
        assert "French" in langs

    # -- subtitles --

    def test_subtitles_present(self, moon):
        assert len(moon.subtitles) >= 4

    def test_english_sdh_subtitle(self, moon):
        assert any("English" in s for s in moon.subtitles)

    def test_eden_lake_subtitles(self, eden_lake):
        assert any("French" in s for s in eden_lake.subtitles)

    # -- packaging --

    def test_packaging(self, moon):
        assert moon.packaging is not None
        assert len(moon.packaging) > 0

    # -- genres --

    def test_genres_present(self, moon):
        assert len(moon.genres) >= 3

    def test_scifi_genre(self, moon):
        assert any("Sci" in g for g in moon.genres)

    # -- community stats --

    def test_popularity_pct(self, moon):
        assert moon.popularity_pct is not None
        assert 0 < moon.popularity_pct <= 100

    def test_collections_count(self, moon):
        assert moon.collections_count is not None
        assert moon.collections_count > 0

    def test_fans_count(self, moon):
        assert moon.fans_count is not None
        assert moon.fans_count > 0


class TestBlurayComClientMethods:
    """Test get_edition_by_url and get_edition via mocked session."""

    def test_get_edition_by_url(self, monkeypatch):
        html = _html("bluray_com_moon_17549.html")
        client = BlurayComClient()
        monkeypatch.setattr(client._session, "get",
                            lambda *a, **kw: _Resp(text=html))
        ed = client.get_edition_by_url("https://www.blu-ray.com/movies/Moon-Blu-ray/17549/")
        assert ed is not None
        assert ed.video_codec == "MPEG-4 AVC"

    def test_get_edition_returns_none_on_404(self, monkeypatch):
        client = BlurayComClient()
        monkeypatch.setattr(client._session, "get",
                            lambda *a, **kw: _Resp(text="<html><title>No such movie</title></html>"))
        ed = client.get_edition_by_url("https://www.blu-ray.com/movies/Fake/99999/")
        assert ed is None

    def test_get_edition_raises_propagated(self, monkeypatch):
        client = BlurayComClient()

        def _fail(*a, **kw):
            r = _Resp(status=503)
            r.raise_for_status()

        monkeypatch.setattr(client._session, "get", _fail)
        with pytest.raises(RuntimeError):
            client.get_edition_by_url("https://www.blu-ray.com/movies/Moon-Blu-ray/17549/")


# ===========================================================================
# DVDCompare
# ===========================================================================


class TestDVDCompareParser:
    """Parse real fixture HTML — no network."""

    @pytest.fixture()
    def alien(self) -> DVDCompareEdition:
        client = DVDCompareClient()
        soup = _soup("dvdcompare_alien_bluray_fid16880.html")
        return client._parse_edition_page(
            soup, "https://www.dvdcompare.net/comparisons/film.php?fid=16880")

    @pytest.fixture()
    def aliens(self) -> DVDCompareEdition:
        client = DVDCompareClient()
        soup = _soup("dvdcompare_aliens_bluray_fid16881.html")
        return client._parse_edition_page(
            soup, "https://www.dvdcompare.net/comparisons/film.php?fid=16881")

    # -- film-level identity --

    def test_title(self, alien):
        assert "Alien" in alien.title

    def test_dvdcompare_id(self, alien):
        assert alien.dvdcompare_id == "16880"

    def test_imdb_id(self, alien):
        assert alien.imdb_id == "tt0078748"

    def test_director(self, alien):
        assert alien.director == "Ridley Scott"

    def test_tagline(self, alien):
        assert alien.tagline is not None
        assert len(alien.tagline) > 5

    # -- cuts / version --

    def test_version_label_multiple(self, alien):
        assert "Director" in alien.version and "Theatrical" in alien.version

    def test_version_differences_text(self, alien):
        assert alien.version_differences is not None
        assert len(alien.version_differences) > 20

    def test_cut_runtimes_unique(self, alien):
        cuts = {c.cut for c in alien.cut_runtimes}
        assert len(cuts) == len(alien.cut_runtimes)   # no duplicates

    def test_theatrical_runtime(self, alien):
        th = next(c for c in alien.cut_runtimes if "theatrical" in c.cut.lower())
        assert th.runtime_seconds == 6997           # 116:37

    def test_directors_cut_runtime(self, alien):
        dc = next(c for c in alien.cut_runtimes if "director" in c.cut.lower())
        assert dc.runtime_seconds == 6949           # 115:49

    # -- releases list --

    def test_releases_count(self, alien):
        assert len(alien.releases) >= 10

    def test_first_release_is_dvdcompare_release(self, alien):
        assert isinstance(alien.releases[0], DVDCompareRelease)

    def test_release_region_parsed(self, alien):
        regions = {r.region for r in alien.releases if r.region}
        assert len(regions) > 1

    def test_edition_name_extracted(self, alien):
        # Release 1 is the H.R. Giger Tribute Collection
        r1 = alien.releases[0]
        assert r1.edition_name is not None
        assert "Giger" in r1.edition_name

    # -- per-release technical fields (America release = index 2) --

    @pytest.fixture()
    def america(self, alien) -> DVDCompareRelease:
        return alien.releases[2]

    def test_country(self, america):
        assert america.country == "America"

    def test_distributor(self, america):
        assert america.distributor is not None
        assert "Fox" in america.distributor or "Twentieth" in america.distributor

    def test_disc_format(self, america):
        assert america.disc_format == "Blu-ray"

    def test_region_all(self, america):
        assert america.region == "ALL"

    def test_aspect_ratio(self, america):
        assert america.aspect_ratio == "2.40:1"

    def test_picture_format(self, america):
        assert america.picture_format is not None
        assert "1080" in america.picture_format
        assert "AVC" in america.picture_format

    def test_case_type(self, america):
        assert america.case_type == "Keep Case"

    def test_soundtrack_present(self, america):
        assert len(america.soundtrack) >= 3

    def test_english_dts_soundtrack(self, america):
        assert any("DTS" in s and "English" in s for s in america.soundtrack)

    def test_subtitles_present(self, america):
        assert len(america.subtitles) >= 5

    def test_danish_subtitle(self, america):
        assert "Danish" in america.subtitles

    def test_extras_present(self, america):
        assert len(america.extras) >= 1

    def test_extras_first_entry(self, america):
        assert "Alien" in america.extras[0]

    def test_notes_present(self, america):
        assert america.notes is not None
        assert len(america.notes) > 10

    def test_notes_mention_reissue(self, america):
        assert "reissued" in america.notes.lower()

    # -- aliens fixture (second title for cross-check) --

    def test_aliens_title(self, aliens):
        assert "Aliens" in aliens.title

    def test_aliens_has_extended_version(self, aliens):
        assert aliens.version is not None
        # Aliens has Theatrical + Special Edition
        cuts = {c.cut.lower() for c in aliens.cut_runtimes}
        assert any("theatrical" in c for c in cuts)

    def test_aliens_releases_count(self, aliens):
        assert len(aliens.releases) >= 5


class TestDVDCompareSearch:
    """Test search() using the captured search-results fixture."""

    def test_search_returns_list(self, monkeypatch):
        html = _html("dvdcompare_search_alien.html")
        client = DVDCompareClient()

        def fake_post(*a, **kw):
            return _Resp(text=html)

        monkeypatch.setattr(client._session, "post", fake_post)
        results = client.search("Alien")
        assert len(results) > 10

    def test_search_contains_alien_dvd(self, monkeypatch):
        html = _html("dvdcompare_search_alien.html")
        client = DVDCompareClient()
        monkeypatch.setattr(client._session, "post",
                            lambda *a, **kw: _Resp(text=html))
        results = client.search("Alien")
        fids = [r.dvdcompare_id for r in results]
        assert "6" in fids      # Alien (1979) DVD
        assert "16880" in fids  # Alien (1979) Blu-ray

    def test_search_each_result_has_url(self, monkeypatch):
        html = _html("dvdcompare_search_alien.html")
        client = DVDCompareClient()
        monkeypatch.setattr(client._session, "post",
                            lambda *a, **kw: _Resp(text=html))
        for r in client.search("Alien"):
            assert r.url and "dvdcompare.net" in r.url

    def test_get_edition_by_fid(self, monkeypatch):
        html = _html("dvdcompare_alien_bluray_fid16880.html")
        client = DVDCompareClient()
        monkeypatch.setattr(client._session, "get",
                            lambda *a, **kw: _Resp(text=html))
        ed = client.get_edition_by_fid("16880")
        assert ed is not None
        assert ed.director == "Ridley Scott"

    def test_get_edition_returns_skeleton_on_empty(self, monkeypatch):
        # DVDCompare client always returns an edition object; an unrecognised page
        # yields a skeleton with no releases and no imdb_id.
        client = DVDCompareClient()
        monkeypatch.setattr(client._session, "get",
                            lambda *a, **kw: _Resp(text="<html><title>Rewind @ www.dvdcompare.net</title></html>"))
        ed = client.get_edition("https://www.dvdcompare.net/comparisons/film.php?fid=0")
        assert ed is not None
        assert ed.releases == []
        assert ed.imdb_id is None


# ===========================================================================
# Discogs
# ===========================================================================


class TestDiscogsRelease:
    """Parse fixture JSON directly."""

    @pytest.fixture()
    def ministry(self) -> DiscogsRelease:
        return DiscogsRelease.model_validate(_json("discogs_release_1383918.json"))

    # -- identity --

    def test_id(self, ministry):
        assert ministry.id == 1383918

    def test_title(self, ministry):
        assert "Ministry" in ministry.title or "Showing Up" in ministry.title

    def test_year(self, ministry):
        assert ministry.year == 1991

    def test_released_iso(self, ministry):
        assert ministry.released == "1991-06-30"

    def test_released_formatted(self, ministry):
        assert ministry.released_formatted is not None
        assert "1991" in ministry.released_formatted

    def test_country(self, ministry):
        assert ministry.country == "US"

    def test_master_id(self, ministry):
        assert ministry.master_id == 292715

    # -- format details --

    def test_format_details_count(self, ministry):
        assert len(ministry.format_details) >= 1

    def test_format_is_laserdisc(self, ministry):
        assert ministry.format_details[0].name == "Laserdisc"

    def test_format_qty(self, ministry):
        assert ministry.format_details[0].qty == 1

    def test_format_ntsc(self, ministry):
        assert "NTSC" in ministry.format_details[0].descriptions

    def test_format_stereo(self, ministry):
        assert "Stereo" in ministry.format_details[0].descriptions

    def test_format_single_sided(self, ministry):
        assert any("Single" in d for d in ministry.format_details[0].descriptions)

    # -- identifiers --

    def test_identifiers_present(self, ministry):
        assert len(ministry.identifiers) >= 2

    def test_barcode_property(self, ministry):
        bc = ministry.barcode
        assert bc is not None
        assert bc.isdigit()

    def test_barcode_value(self, ministry):
        assert ministry.barcode == "724117910464"

    def test_matrix_runout_present(self, ministry):
        types = {i.type for i in ministry.identifiers}
        assert "Matrix / Runout" in types

    # -- community --

    def test_community_not_none(self, ministry):
        assert ministry.community is not None

    def test_community_have(self, ministry):
        assert ministry.community.have > 0

    def test_community_want(self, ministry):
        assert ministry.community.want > 0

    def test_community_rating_count(self, ministry):
        assert ministry.community.rating_count > 0

    def test_community_rating_average(self, ministry):
        assert ministry.community.rating_average is not None
        assert 1.0 <= ministry.community.rating_average <= 5.0

    def test_community_data_quality(self, ministry):
        assert ministry.community.data_quality is not None

    # -- metadata --

    def test_genres(self, ministry):
        assert len(ministry.genres) >= 1

    def test_styles(self, ministry):
        assert len(ministry.styles) >= 1

    def test_label_names(self, ministry):
        assert "Lumivision" in ministry.label_names

    def test_artist_names(self, ministry):
        assert "Ministry" in ministry.artist_names

    def test_tracklist_count(self, ministry):
        assert len(ministry.tracklist) >= 1

    def test_num_for_sale(self, ministry):
        assert ministry.num_for_sale is not None and ministry.num_for_sale >= 0

    # -- images --

    def test_primary_image_url(self, ministry):
        url = ministry.primary_image_url
        assert url and url.startswith("https://")

    def test_thumbnail_url(self, ministry):
        url = ministry.thumbnail_url
        assert url and url.startswith("https://")


class TestDiscogsSearchHit:
    """Parse search fixture."""

    @pytest.fixture()
    def hits(self):
        data = _json("discogs_search_alien_laserdisc.json")
        return [DiscogsSearchHit.model_validate(r) for r in data.get("results", [])]

    def test_at_least_one_result(self, hits):
        assert len(hits) >= 1

    def test_hit_id(self, hits):
        assert all(isinstance(h.id, int) for h in hits)

    def test_hit_title(self, hits):
        assert all(h.title for h in hits)

    def test_hit_year_is_int_or_none(self, hits):
        for h in hits:
            assert h.year is None or isinstance(h.year, int)

    def test_ministry_hit_id(self, hits):
        ids = [h.id for h in hits]
        assert 1383918 in ids


class TestDiscogsClientMethods:
    """Test all client methods via monkeypatching."""

    @pytest.fixture()
    def client(self) -> DiscogsClient:
        return DiscogsClient()

    def test_get_release(self, client, monkeypatch):
        data = _json("discogs_release_1383918.json")
        monkeypatch.setattr(client._session, "get",
                            lambda *a, **kw: _Resp(data=data))
        rel = client.get_release(1383918)
        assert rel is not None
        assert rel.id == 1383918
        assert rel.barcode == "724117910464"

    def test_get_release_returns_none_on_error(self, client, monkeypatch):
        def _fail(*a, **kw):
            raise RuntimeError("network error")

        monkeypatch.setattr(client._session, "get", _fail)
        assert client.get_release(9999999) is None

    def test_search(self, client, monkeypatch):
        data = _json("discogs_search_alien_laserdisc.json")
        monkeypatch.setattr(client._session, "get",
                            lambda *a, **kw: _Resp(data=data))
        hits = client.search("Alien", fmt="Laserdisc")
        assert len(hits) >= 1
        assert all(isinstance(h, DiscogsSearchHit) for h in hits)

    def test_search_video_tries_non_music_first(self, client, monkeypatch):
        calls = []
        data = _json("discogs_search_alien_laserdisc.json")

        def _fake_get(url, params=None, **kw):
            calls.append(params or {})
            return _Resp(data=data)

        monkeypatch.setattr(client._session, "get", _fake_get)
        client.search_video("Ministry", fmt="Laserdisc")
        assert calls[0].get("genre") == "Non-Music"

    def test_search_video_falls_back_on_empty(self, client, monkeypatch):
        # search_video() does two passes: Non-Music (auto-applied by search())
        # then Stage & Screen.  Both passes also filter out results that carry
        # music genres (Electronic, Rock, …).  The fixture contains a Ministry
        # concert LaserDisc (Electronic + Rock) so it is filtered out of both
        # passes, yielding an empty result — which is correct behaviour.
        call_count = 0
        empty = {"results": [], "pagination": {}}
        data = _json("discogs_search_alien_laserdisc.json")

        def _fake_get(url, params=None, **kw):
            nonlocal call_count
            call_count += 1
            return _Resp(data=empty if call_count == 1 else data)

        monkeypatch.setattr(client._session, "get", _fake_get)
        hits = client.search_video("Ministry", fmt="Laserdisc")
        assert call_count == 2             # fallback still fires
        assert hits == []                  # music result filtered out

    def test_search_video_passes_non_music_result(self, client, monkeypatch):
        # A result with only Non-Music genre (no music genres) should be returned.
        video_result = {
            "results": [{
                "id": 999999, "title": "Pink Floyd Live at Pompeii", "uri": "/releases/999999",
                "cover_image": "", "year": "1974",
                "format": ["Laserdisc"], "label": ["Polygram"],
                "country": "US", "catno": "PF-001",
                "genre": ["Non-Music"], "style": ["Concert Film"],
                "master_id": None,
            }],
            "pagination": {},
        }
        monkeypatch.setattr(client._session, "get",
                            lambda *a, **kw: _Resp(data=video_result))
        hits = client.search_video("Pink Floyd", fmt="Laserdisc")
        assert len(hits) == 1
        assert hits[0].id == 999999

    def test_search_film_is_alias_for_search_video(self, client, monkeypatch):
        # search_film() is a deprecated alias — verify it delegates to search_video()
        called_with = []
        orig = client.search_video

        def _spy(*args, **kwargs):
            called_with.append((args, kwargs))
            return []

        monkeypatch.setattr(client, "search_video", _spy)
        client.search_film("test", fmt="VHS", per_page=3)
        assert len(called_with) == 1
        assert called_with[0][1] == {"fmt": "VHS", "per_page": 3}

    def test_get_master(self, client, monkeypatch):
        data = _json("discogs_master_292715.json")
        monkeypatch.setattr(client._session, "get",
                            lambda *a, **kw: _Resp(data=data))
        result = client.get_master(292715)
        assert result is not None
        assert result.get("id") == 292715

    def test_get_master_returns_none_on_error(self, client, monkeypatch):
        def _fail(*a, **kw):
            raise RuntimeError("timeout")

        monkeypatch.setattr(client._session, "get", _fail)
        assert client.get_master(292715) is None

    def test_get_master_versions(self, client, monkeypatch):
        data = _json("discogs_master_292715_versions.json")
        monkeypatch.setattr(client._session, "get",
                            lambda *a, **kw: _Resp(data=data))
        versions = client.get_master_versions(292715)
        assert isinstance(versions, list)
        assert len(versions) >= 1

    def test_get_master_versions_returns_empty_on_error(self, client, monkeypatch):
        def _fail(*a, **kw):
            raise RuntimeError("timeout")

        monkeypatch.setattr(client._session, "get", _fail)
        assert client.get_master_versions(292715) == []

    def test_rate_limit_registered_with_transport(self, client):
        """The client registers its per-host interval with the shared limiter."""
        from metadatarr import transport

        assert transport._GLOBAL_LIMITER._per_host["api.discogs.com"] == client._min_interval


# ===========================================================================
# Model-level tests (no HTTP at all)
# ===========================================================================


class TestDiscogsFormatDetail:
    def test_from_dict(self):
        fd = DiscogsFormatDetail(
            name="Laserdisc", qty=1,
            descriptions=["12\"", "NTSC", "CLV"], text=None)
        assert fd.name == "Laserdisc"
        assert "NTSC" in fd.descriptions

    def test_qty_optional(self):
        fd = DiscogsFormatDetail(name="VHS")
        assert fd.qty is None
        assert fd.descriptions == []


class TestDiscogsCommunity:
    def test_defaults(self):
        c = DiscogsCommunity()
        assert c.have == 0
        assert c.want == 0
        assert c.rating_average is None

    def test_populated(self):
        c = DiscogsCommunity(have=10, want=5, rating_count=3, rating_average=4.5)
        assert c.rating_average == 4.5


class TestDiscogsIdentifier:
    def test_barcode(self):
        i = DiscogsIdentifier(type="Barcode", value="123456789", description="Scanned")
        assert i.type == "Barcode"
        assert i.description == "Scanned"

    def test_matrix(self):
        i = DiscogsIdentifier(type="Matrix / Runout", value="SIDE-A")
        assert i.description is None


class TestDVDCompareRelease:
    def test_defaults(self):
        r = DVDCompareRelease()
        assert r.soundtrack == []
        assert r.subtitles == []
        assert r.extras == []

    def test_populated(self):
        r = DVDCompareRelease(
            disc_format="Blu-ray", region="ALL", country="Germany",
            distributor="Studiocanal", aspect_ratio="2.39:1",
            picture_format="1080p24 AVC MPEG-4", case_type="Keep Case",
            soundtrack=["German DTS-HD MA 5.1"],
            subtitles=["German", "English"],
        )
        assert r.distributor == "Studiocanal"
        assert "German" in r.subtitles


class TestBlurayComAudioTrack:
    def test_full_track(self):
        t = BlurayComAudioTrack(
            codec="DTS-HD Master Audio", channels="7.1",
            language="English", sample_rate_khz=48.0, bit_depth=24,
            is_descriptive=False)
        assert t.sample_rate_khz == 48.0
        assert t.bit_depth == 24

    def test_descriptive_flag(self):
        t = BlurayComAudioTrack(language="English", is_descriptive=True)
        assert t.is_descriptive is True

    def test_defaults(self):
        t = BlurayComAudioTrack()
        assert t.is_descriptive is False
        assert t.bitrate_kbps is None
