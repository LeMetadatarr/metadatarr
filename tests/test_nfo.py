# SPDX-License-Identifier: Apache-2.0
"""Tests for metadatarr.nfo — .nfo sidecar XML generation."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from mediavocab.models import ExternalIds

from metadatarr.nfo import nfo_xml


def test_music_entry_produces_musicvideo_root():
    xml = nfo_xml(
        title="Avril 14th", media_kind="music", artist="Aphex Twin",
        album="Drukqs", tags=["idm", "electronic"], thumbnail="https://x/t.jpg",
    )
    root = ET.fromstring(xml)
    assert root.tag == "musicvideo"
    assert root.findtext("title") == "Avril 14th"
    assert root.findtext("artist") == "Aphex Twin"
    assert root.findtext("album") == "Drukqs"
    assert "idm" in [g.text for g in root.findall("genre")]
    assert "idm" in [g.text for g in root.findall("tag")]
    assert root.findtext("thumb") == "https://x/t.jpg"


def test_movie_entry_produces_movie_root():
    xml = nfo_xml(title="Talk", media_kind="movie", artist="Some Channel")
    root = ET.fromstring(xml)
    assert root.tag == "movie"
    assert root.findtext("studio") == "Some Channel"


def test_episodic_without_season_episode_falls_back_to_movie():
    root = ET.fromstring(nfo_xml(title="Old Film", media_kind="episodic"))
    assert root.tag == "movie"


def test_episodic_with_season_episode_is_episodedetails():
    root = ET.fromstring(nfo_xml(title="Ep", media_kind="episodic", season=1, episode=2))
    assert root.tag == "episodedetails"
    assert root.findtext("season") == "1"
    assert root.findtext("episode") == "2"


def test_xml_is_well_formed_and_has_header():
    xml = nfo_xml(title="Demo Title")
    assert xml.startswith("<?xml")
    ET.fromstring(xml)  # raises if malformed


def test_text_is_escaped():
    xml = nfo_xml(title="Rock & Roll <Live>")
    assert "Rock & Roll <Live>" not in xml
    assert "&amp;" in xml
    root = ET.fromstring(xml)  # would raise if the escaping broke the XML
    assert root.findtext("title") == "Rock & Roll <Live>"


def test_thumbnail_present_when_set():
    root = ET.fromstring(nfo_xml(title="X", thumbnail="https://x/pic.jpg"))
    assert root.findtext("thumb") == "https://x/pic.jpg"


def test_thumbnail_omitted_when_none():
    root = ET.fromstring(nfo_xml(title="X", thumbnail=None))
    assert root.find("thumb") is None


def test_runtime_and_year_derived():
    root = ET.fromstring(nfo_xml(title="X", runtime=185.0, year=2021))
    assert root.findtext("runtime") == "3"
    assert root.findtext("year") == "2021"


def test_no_year_omits_year_tag():
    root = ET.fromstring(nfo_xml(title="X", year=None))
    assert root.find("year") is None


def test_uniqueids_mapped_from_external_ids():
    ids = ExternalIds.model_validate({"tmdb_movie": 700391, "imdb": "tt0765443"})
    root = ET.fromstring(nfo_xml(title="65", media_kind="movie", external_ids=ids))
    uids = {el.get("type"): el.text for el in root.findall("uniqueid")}
    assert uids.get("tmdb") == "700391"
    assert uids.get("imdb") == "tt0765443"


def test_uniqueids_omitted_for_music():
    ids = ExternalIds.model_validate({"tmdb_movie": 1})
    root = ET.fromstring(nfo_xml(title="X", media_kind="music", external_ids=ids))
    assert root.findall("uniqueid") == []


def test_uniqueid_youtube_emitted_from_extra():
    ids = ExternalIds.model_validate({"extra": {"youtube": "dQw4w9WgXcQ"}})
    xml = nfo_xml(title="Some Talk", media_kind="movie", external_ids=ids)
    root = ET.fromstring(xml)  # raises if malformed
    uids = {el.get("type"): el.text for el in root.findall("uniqueid")}
    assert uids.get("youtube") == "dQw4w9WgXcQ"


def test_uniqueid_youtube_combined_with_catalog_ids():
    ids = ExternalIds.model_validate({
        "tmdb_movie": 700391, "extra": {"youtube": "abc12345678"},
    })
    root = ET.fromstring(nfo_xml(title="65", media_kind="movie", external_ids=ids))
    uids = {el.get("type"): el.text for el in root.findall("uniqueid")}
    assert uids.get("tmdb") == "700391"
    assert uids.get("youtube") == "abc12345678"
