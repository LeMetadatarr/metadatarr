# SPDX-License-Identifier: Apache-2.0
"""Tests for metadatarr.library — local media-library tagger.

No real network access: metadatarr.resolve/enrich are always monkeypatched.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

from metadatarr import library
from mediavocab import MediaType
from mediavocab.models.signals import Signals


# ---------------------------------------------------------------------------
# scan()
# ---------------------------------------------------------------------------

def _touch(path: Path, content: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_scan_finds_video_and_music_and_ignores_other_files(tmp_path):
    _touch(tmp_path / "Movies" / "Big Buck Bunny (2008).mp4")
    _touch(tmp_path / "Music" / "Aphex Twin - Avril 14th.mp3")
    _touch(tmp_path / "Movies" / "poster.jpg")
    _touch(tmp_path / "Movies" / "Big Buck Bunny (2008).srt")

    found = {f.path.name: f.kind for f in library.scan(str(tmp_path))}
    assert found == {
        "Big Buck Bunny (2008).mp4": "video",
        "Aphex Twin - Avril 14th.mp3": "music",
    }


def test_scan_respects_media_filter(tmp_path):
    _touch(tmp_path / "a.mkv")
    _touch(tmp_path / "b.flac")

    video_only = list(library.scan(str(tmp_path), media="video"))
    music_only = list(library.scan(str(tmp_path), media="music"))
    assert [f.path.name for f in video_only] == ["a.mkv"]
    assert [f.path.name for f in music_only] == ["b.flac"]


def test_scan_skips_trailer_and_sample_suffixes(tmp_path):
    _touch(tmp_path / "Bar - Trailer-trailer.mkv")
    _touch(tmp_path / "Bar-sample.mkv")
    _touch(tmp_path / "Real Movie (2020).mkv")

    found = {f.path.name for f in library.scan(str(tmp_path))}
    assert found == {"Real Movie (2020).mkv"}


def test_scan_skips_extras_folders(tmp_path):
    _touch(tmp_path / "Trailers" / "x-trailer.mkv")
    _touch(tmp_path / "Extras" / "y.mkv")
    _touch(tmp_path / "Movie (2020).mkv")

    found = {f.path.name for f in library.scan(str(tmp_path))}
    assert found == {"Movie (2020).mkv"}


def test_scan_skip_extras_false_includes_them(tmp_path):
    _touch(tmp_path / "Trailers" / "x-trailer.mkv")
    _touch(tmp_path / "Movie (2020).mkv")

    found = {f.path.name for f in library.scan(str(tmp_path), skip_extras=False)}
    assert found == {"x-trailer.mkv", "Movie (2020).mkv"}


def test_scan_does_not_over_match_legit_titles_containing_sample_word():
    assert library._is_extra_path(Path("/lib/The Sample Case (2020).mkv")) is False
    assert library._is_extra_path(Path("/lib/Sample.mkv")) is False


def test_scan_reports_skipped_extras_count(tmp_path):
    _touch(tmp_path / "Trailers" / "x-trailer.mkv")
    _touch(tmp_path / "y-sample.mkv")
    _touch(tmp_path / "Movie (2020).mkv")

    stats: dict = {}
    found = list(library.scan(str(tmp_path), stats=stats))
    assert len(found) == 1
    assert stats["skipped_extras"] == 2


# ---------------------------------------------------------------------------
# extract_signals() — filename fallback (guessit/mutagen absent)
# ---------------------------------------------------------------------------

def test_extract_signals_movie_filename_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    f = library.LocalMediaFile(path=_touch(tmp_path / "Inception (2010).mkv"), kind="video")
    signals = library.extract_signals(f)
    assert signals.title == "Inception"
    assert signals.year == 2010
    assert signals.medium == MediaType.MOVIE


def test_extract_signals_tv_filename_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    f = library.LocalMediaFile(path=_touch(tmp_path / "Show.Name.S01E02.mkv"), kind="video")
    signals = library.extract_signals(f)
    assert signals.season == 1
    assert signals.episode == 2
    assert signals.medium == MediaType.EPISODIC_SERIES
    assert "Show" in (signals.title or "")


def test_extract_signals_music_filename_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_mutagen", None)
    f = library.LocalMediaFile(path=_touch(tmp_path / "Artist - Song.mp3"), kind="music")
    signals = library.extract_signals(f)
    assert signals.artist == "Artist"
    assert signals.title == "Song"
    assert signals.medium == MediaType.MUSIC


def test_extract_signals_music_reads_embedded_tags_when_mutagen_present(tmp_path, monkeypatch):
    fake_tags = {"title": ["Real Title"], "artist": ["Real Artist"], "date": ["2015-01-01"]}

    class _FakeAudio:
        tags = fake_tags

    class _FakeMutagenModule:
        @staticmethod
        def File(path, easy=True):
            return _FakeAudio()

    monkeypatch.setattr(library, "_mutagen", _FakeMutagenModule())
    f = library.LocalMediaFile(path=_touch(tmp_path / "whatever.mp3"), kind="music")
    signals = library.extract_signals(f)
    assert signals.title == "Real Title"
    assert signals.artist == "Real Artist"
    assert signals.year == 2015


# ---------------------------------------------------------------------------
# extract_embedded_ids() — including the #46 fix
# ---------------------------------------------------------------------------

def test_extract_embedded_ids_tmdb_braces():
    ids = library.extract_embedded_ids("The Adam Project (2022) {tmdb-696806} [WEBDL-1080p].mkv")
    assert ids is not None
    assert ids.tmdb_movie == 696806


def test_extract_embedded_ids_tmdbid_braces():
    ids = library.extract_embedded_ids("65 (2023) {tmdbid-700391}.mkv")
    assert ids is not None
    assert ids.tmdb_movie == 700391


def test_extract_embedded_ids_tmdbid_brackets():
    ids = library.extract_embedded_ids("The Boogeyman (2023) [tmdbid-532408].mkv")
    assert ids is not None
    assert ids.tmdb_movie == 532408


def test_extract_embedded_ids_imdb_braces():
    ids = library.extract_embedded_ids("Movie (2020) {imdb-tt1254207}.mkv")
    assert ids is not None
    assert ids.imdb == "tt1254207"


def test_extract_embedded_ids_imdbid_brackets():
    ids = library.extract_embedded_ids("Movie (2020) [imdbid-tt1254207].mkv")
    assert ids is not None
    assert ids.imdb == "tt1254207"


def test_extract_embedded_ids_tvdb_braces():
    ids = library.extract_embedded_ids("Show (2021) {tvdb-12345}.mkv")
    assert ids is not None
    assert ids.tvdb == 12345


def test_extract_embedded_ids_true_episodic_uses_tmdb_tv():
    ids = library.extract_embedded_ids("Show {tmdb-1234} S01E02.mkv", is_true_episodic=True)
    assert ids is not None
    assert ids.tmdb_tv == 1234
    assert ids.tmdb_movie is None


def test_extract_embedded_ids_no_id_returns_none():
    assert library.extract_embedded_ids("Plain Title (2020).mkv") is None


def test_extract_embedded_ids_false_positive_empty_tag_returns_none():
    assert library.extract_embedded_ids("Movie {tmdb-} garbage (1984).mkv") is None


def test_extract_embedded_ids_year_alone_not_mistaken_for_id():
    assert library.extract_embedded_ids("1984 (1984).mkv") is None


def test_extract_embedded_ids_numeric_title_defaults_to_tmdb_movie_not_tv():
    """PR#46 regression: a numeric title like "65 (2023)" with no real SxxEyy
    marker must default to tmdb_movie even if a shaky type-guesser (e.g.
    guessit) might mistake it for an episode. This is exercised at the
    tag_file level (test_tag_file_numeric_title_bugfix_46 below) where the
    is_true_episodic gate is actually computed from the filename."""
    ids = library.extract_embedded_ids("65 (2023) {tmdb-700391}.mkv", is_true_episodic=False)
    assert ids is not None
    assert ids.tmdb_movie == 700391
    assert ids.tmdb_tv is None


def test_extract_embedded_ids_tvdb_always_maps_to_tv_catalog():
    ids = library.extract_embedded_ids("Show S01E02 {tvdb-12345}.mkv", is_true_episodic=False)
    assert ids is not None
    assert ids.tvdb == 12345


# ---------------------------------------------------------------------------
# extract_youtube_id() — yt-dlp / TubeArchivist / tubesync filenames
# ---------------------------------------------------------------------------

def test_extract_youtube_id_bracketed_yt_dlp_form():
    assert library.extract_youtube_id("Some Talk [dQw4w9WgXcQ].mp4") == "dQw4w9WgXcQ"


def test_extract_youtube_id_bare_tubearchivist_form():
    assert library.extract_youtube_id("dQw4w9WgXcQ.mp4") == "dQw4w9WgXcQ"


def test_extract_youtube_id_underscore_delimited_tubesync_form():
    assert library.extract_youtube_id("Some_Show_d558tMKjvgc_720p.mp4") == "d558tMKjvgc"


def test_extract_youtube_id_release_tag_bracket_returns_none():
    assert library.extract_youtube_id("Movie (2020) [Bluray-1080p].mkv") is None


def test_extract_youtube_id_ten_char_bracket_returns_none():
    assert library.extract_youtube_id("[abcdefghij].mkv") is None


def test_extract_youtube_id_twelve_char_bracket_returns_none():
    assert library.extract_youtube_id("[abcdefghijkl].mkv") is None


def test_extract_youtube_id_normal_movie_name_returns_none():
    assert library.extract_youtube_id("Movie (2020).mkv") is None


def test_extract_youtube_id_bare_stem_wrong_length_returns_none():
    assert library.extract_youtube_id("dQw4w9WgXc.mp4") is None


# ---------------------------------------------------------------------------
# tag_file()
# ---------------------------------------------------------------------------

def _fake_resolve_result(signals, external_ids):
    return SimpleNamespace(signals=signals, external_ids=external_ids)


class _FakeExternalIds:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return dict(self._data)


def test_tag_file_writes_nfo_on_match(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    f = library.LocalMediaFile(path=path, kind="video")

    def fake_resolve(signals, *, max_workers=8):
        merged = Signals(title="Big Buck Bunny", year=2008, medium=MediaType.MOVIE)
        return _fake_resolve_result(merged, _FakeExternalIds({"imdb": "tt1254207"}))

    monkeypatch.setattr(library, "resolve", fake_resolve)
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.action == "wrote"
    assert result.matched is True
    assert result.external_ids == {"imdb": "tt1254207"}
    nfo_path = path.with_suffix(".nfo")
    assert nfo_path.exists()
    root = ET.fromstring(nfo_path.read_text())
    assert root.tag == "movie"
    assert root.findtext("title") == "Big Buck Bunny"
    ids = {el.get("type"): el.text for el in root.findall("uniqueid")}
    assert ids.get("imdb") == "tt1254207"


def test_tag_file_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    f = library.LocalMediaFile(path=path, kind="video")

    def fake_resolve(signals, *, max_workers=8):
        merged = Signals(title="Big Buck Bunny", year=2008, medium=MediaType.MOVIE)
        return _fake_resolve_result(merged, _FakeExternalIds({"imdb": "tt1254207"}))

    monkeypatch.setattr(library, "resolve", fake_resolve)
    result = library.tag_file(f, write_nfo=True, dry_run=True)

    assert result.action == "would-write"
    assert not path.with_suffix(".nfo").exists()


def test_tag_file_resolve_exception_is_graceful(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Inception (2010).mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    def fake_resolve(signals, *, max_workers=8):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(library, "resolve", fake_resolve)
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.action in ("wrote", "error")
    if result.action == "wrote":
        assert result.matched is False
        assert result.external_ids is None


def test_tag_file_resolve_hard_error_before_signals_never_crashes(tmp_path, monkeypatch):
    """If extract_signals itself blows up, tag_file reports 'error', not a crash."""
    path = _touch(tmp_path / "whatever.mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    def boom(_file):
        raise ValueError("boom")

    monkeypatch.setattr(library, "extract_signals", boom)
    result = library.tag_file(f, write_nfo=True, dry_run=False)
    assert result.action == "error"
    assert not path.with_suffix(".nfo").exists()


def test_tag_file_low_match_falls_back_to_minimal_nfo(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Some Obscure Home Video (2019).mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    def fake_resolve(signals, *, max_workers=8):
        return _fake_resolve_result(None, None)

    monkeypatch.setattr(library, "resolve", fake_resolve)
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.action == "wrote"
    assert result.matched is False
    assert result.external_ids is None
    nfo_path = path.with_suffix(".nfo")
    assert nfo_path.exists()
    root = ET.fromstring(nfo_path.read_text())
    assert root.findtext("title") == "Some Obscure Home Video"


def test_tag_file_never_modifies_media_file_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    content = b"not really a video but bytes must survive"
    path = _touch(tmp_path / "Movie (2001).mkv", content)
    f = library.LocalMediaFile(path=path, kind="video")

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: _fake_resolve_result(None, None))
    library.tag_file(f, write_nfo=True, dry_run=False)

    assert path.read_bytes() == content
    siblings = {p.name for p in path.parent.iterdir()}
    assert siblings == {"Movie (2001).mkv", "Movie (2001).nfo"}


def test_tag_file_never_writes_outside_root(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    root = tmp_path / "library"
    path = _touch(root / "Movie (2001).mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: _fake_resolve_result(None, None))
    library.tag_file(f, write_nfo=True, dry_run=False)

    nfo = path.with_suffix(".nfo")
    assert nfo.parent == root
    assert nfo.exists()


def test_episodedetails_nfo_for_tv_file(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Show.Name.S01E02.mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: _fake_resolve_result(None, None))
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.action == "wrote"
    root = ET.fromstring(result.nfo_path.read_text())
    assert root.tag == "episodedetails"
    assert root.findtext("season") == "1"
    assert root.findtext("episode") == "2"


def test_musicvideo_nfo_for_music_file(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_mutagen", None)
    path = _touch(tmp_path / "Artist - Song.mp3")
    f = library.LocalMediaFile(path=path, kind="music")

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: _fake_resolve_result(None, None))
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.action == "wrote"
    root = ET.fromstring(result.nfo_path.read_text())
    assert root.tag == "musicvideo"
    assert root.findtext("artist") == "Artist"


# ---------------------------------------------------------------------------
# tag_file() — embedded-id direct match, incl. #46 bugfix
# ---------------------------------------------------------------------------

class _FakeExpandedExternalIds:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return dict(self._data)


def test_tag_file_uses_embedded_id_and_enriches(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "65 (2023) {tmdb-700391}.mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    resolve_calls = []
    enrich_calls = []

    def fake_resolve(signals, *, max_workers=8):
        resolve_calls.append(signals)
        raise AssertionError("resolve() must not be called when an embedded id is present")

    def fake_enrich(seed, *, medium=None, apply_maps=True, max_workers=8):
        enrich_calls.append(seed)
        return _FakeExpandedExternalIds({"tmdb_movie": 700391, "imdb": "tt0765443", "wikidata": "Q104123"})

    monkeypatch.setattr(library, "resolve", fake_resolve)
    monkeypatch.setattr(library, "enrich", fake_enrich)

    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert not resolve_calls
    assert len(enrich_calls) == 1
    assert enrich_calls[0].tmdb_movie == 700391
    assert result.matched is True
    assert result.external_ids == {
        "tmdb_movie": 700391, "imdb": "tt0765443", "wikidata": "Q104123",
    }
    assert result.note == "matched (embedded id)"


def test_tag_file_numeric_title_bugfix_46(tmp_path, monkeypatch):
    """The core PR#46 regression: a numeric title "65 (2023)" with NO real
    SxxEyy marker anywhere in the filename must map its embedded {tmdb-} id
    to tmdb_movie, never tmdb_tv — even if guessit's shaky type guesser
    thinks it looks like an episode number. is_true_episodic is derived
    purely from a real SxxEyy regex match on the filename, not guessit."""
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "65 (2023) {tmdb-700391}.mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    seen_seed = {}

    def fake_enrich(seed, *, medium=None, apply_maps=True, max_workers=8):
        seen_seed["seed"] = seed
        return _FakeExpandedExternalIds({})

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: (_ for _ in ()).throw(
                            AssertionError("resolve() must not be called")))
    monkeypatch.setattr(library, "enrich", fake_enrich)

    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert seen_seed["seed"].tmdb_movie == 700391
    assert seen_seed["seed"].tmdb_tv is None
    assert result.external_ids == {"tmdb_movie": 700391}


def test_tag_file_true_episodic_embedded_id_maps_to_tmdb_tv(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Show {tmdb-1234} S01E02.mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    seen_seed = {}

    def fake_enrich(seed, *, medium=None, apply_maps=True, max_workers=8):
        seen_seed["seed"] = seed
        return _FakeExpandedExternalIds({})

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: (_ for _ in ()).throw(
                            AssertionError("resolve() must not be called")))
    monkeypatch.setattr(library, "enrich", fake_enrich)

    library.tag_file(f, write_nfo=True, dry_run=False)

    assert seen_seed["seed"].tmdb_tv == 1234
    assert seen_seed["seed"].tmdb_movie is None


def test_tag_file_embedded_id_enrich_empty_falls_back_to_raw_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "65 (2023) {tmdb-700391}.mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: (_ for _ in ()).throw(
                            AssertionError("resolve() must not be called")))
    monkeypatch.setattr(library, "enrich",
                        lambda seed, **kw: _FakeExpandedExternalIds({}))

    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.matched is True
    assert result.external_ids == {"tmdb_movie": 700391}
    assert result.note == "matched (embedded id)"


def test_tag_file_embedded_id_enrich_raises_falls_back_to_raw_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "The Boogeyman (2023) {tmdb-532408}.mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: (_ for _ in ()).throw(
                            AssertionError("resolve() must not be called")))

    def boom_enrich(seed, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(library, "enrich", boom_enrich)

    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.matched is True
    assert result.external_ids == {"tmdb_movie": 532408}
    assert result.note == "matched (embedded id)"


def test_tag_file_no_embedded_id_falls_back_to_resolve(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    f = library.LocalMediaFile(path=path, kind="video")

    def fake_resolve(signals, *, max_workers=8):
        merged = Signals(title="Big Buck Bunny", year=2008, medium=MediaType.MOVIE)
        return _fake_resolve_result(merged, _FakeExternalIds({"imdb": "tt1254207"}))

    monkeypatch.setattr(library, "resolve", fake_resolve)
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.matched is True
    assert result.note == "matched"
    assert result.external_ids == {"imdb": "tt1254207"}


# ---------------------------------------------------------------------------
# ffprobe embedded container metadata (title/date, tmdb/imdb tags)
# ---------------------------------------------------------------------------

def _fake_ffprobe_run(tags):
    """A fake ``subprocess.run`` returning an ffprobe-shaped JSON stdout."""
    payload = json.dumps({"format": {"tags": tags}})

    def _run(cmd, *, capture_output=True, text=True, timeout=None, check=False):
        return SimpleNamespace(stdout=payload, returncode=0)
    return _run


def test_extract_signals_uses_ffprobe_embedded_title(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    monkeypatch.setattr(library.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(library.subprocess, "run",
                        _fake_ffprobe_run({"title": "Correct Title"}))

    f = library.LocalMediaFile(
        path=_touch(tmp_path / "messy.file.name.2010.mkv"), kind="video")
    signals = library.extract_signals(f)
    assert signals.title == "Correct Title"


def test_extract_signals_uses_ffprobe_date_when_filename_has_no_year(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    monkeypatch.setattr(library.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(library.subprocess, "run",
                        _fake_ffprobe_run({"title": "Some Title", "date": "2015-03-01"}))

    f = library.LocalMediaFile(
        path=_touch(tmp_path / "Some Title.mkv"), kind="video")
    signals = library.extract_signals(f)
    assert signals.title == "Some Title"
    assert signals.year == 2015


def test_extract_signals_ffprobe_absent_falls_back_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    monkeypatch.setattr(library.shutil, "which", lambda name: None)

    def _run_should_not_be_called(*a, **kw):
        raise AssertionError("subprocess.run must not be called when ffprobe is absent")
    monkeypatch.setattr(library.subprocess, "run", _run_should_not_be_called)

    f = library.LocalMediaFile(
        path=_touch(tmp_path / "Inception (2010).mkv"), kind="video")
    signals = library.extract_signals(f)
    assert signals.title == "Inception"
    assert signals.year == 2010


def test_tag_file_uses_ffprobe_embedded_tmdb_id(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    monkeypatch.setattr(library.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(library.subprocess, "run",
                        _fake_ffprobe_run({"title": "Some Movie", "tmdb": "12345"}))

    def fake_enrich(seed, *, medium=None, apply_maps=True, max_workers=8):
        return _FakeExpandedExternalIds({"tmdb_movie": 12345})

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: (_ for _ in ()).throw(
                            AssertionError("resolve() must not be called when an embedded id is present")))
    monkeypatch.setattr(library, "enrich", fake_enrich)

    path = _touch(tmp_path / "Some Movie.mkv")  # no filename id -> falls back to ffprobe tag
    f = library.LocalMediaFile(path=path, kind="video")
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.matched is True
    assert result.external_ids == {"tmdb_movie": 12345}


# ---------------------------------------------------------------------------
# Subtitle-truncation fix: "Title - Subtitle (Year)" must not resolve as
# just "Title" (real-library finding: guessit truncates "The Lord of the
# Rings - The Two Towers" down to "The Lord of the Rings").
# ---------------------------------------------------------------------------

def test_tag_file_retries_with_full_title_when_truncated_title_has_no_match(tmp_path, monkeypatch):
    monkeypatch.setattr(library.shutil, "which", lambda name: None)  # no ffprobe in play

    # Simulate guessit truncating the subtitle off the title.
    def fake_guessit_signals(path):
        return Signals(title="The Lord of the Rings", year=2002, medium=MediaType.MOVIE)
    monkeypatch.setattr(library, "_guessit_video_signals", fake_guessit_signals)

    seen_titles = []

    def fake_resolve(signals, *, max_workers=8):
        seen_titles.append(signals.title)
        if signals.title == "The Lord of the Rings: The Two Towers":
            merged = Signals(title="The Lord of the Rings: The Two Towers",
                             year=2002, medium=MediaType.MOVIE)
            return _fake_resolve_result(merged, _FakeExternalIds({"tmdb_movie": 121}))
        # The truncated title alone finds nothing.
        return _fake_resolve_result(None, None)

    monkeypatch.setattr(library, "resolve", fake_resolve)
    monkeypatch.setattr(library, "_full_title_candidate",
                        lambda stem: "The Lord of the Rings: The Two Towers")

    path = _touch(tmp_path / "The Lord of the Rings - The Two Towers (2002) WEBDL-1080p.mkv")
    f = library.LocalMediaFile(path=path, kind="video")
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert seen_titles == ["The Lord of the Rings", "The Lord of the Rings: The Two Towers"]
    assert result.matched is True
    assert result.external_ids == {"tmdb_movie": 121}
    assert result.note == "matched (full-title retry)"


def test_tag_file_no_retry_needed_when_first_title_already_matches(tmp_path, monkeypatch):
    """Regression: a clean title (e.g. Stargate) must match on the first
    attempt and never trigger a needless second resolve() call."""
    monkeypatch.setattr(library, "_guessit", None)
    monkeypatch.setattr(library.shutil, "which", lambda name: None)

    resolve_calls = []

    def fake_resolve(signals, *, max_workers=8):
        resolve_calls.append(signals.title)
        merged = Signals(title="Stargate", year=1994, medium=MediaType.MOVIE)
        return _fake_resolve_result(merged, _FakeExternalIds({"tmdb_movie": 2164}))

    monkeypatch.setattr(library, "resolve", fake_resolve)

    path = _touch(tmp_path / "Stargate (1994).mkv")
    f = library.LocalMediaFile(path=path, kind="video")
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert resolve_calls == ["Stargate"]  # only one attempt
    assert result.matched is True
    assert result.external_ids == {"tmdb_movie": 2164}


def test_tag_file_full_title_retry_no_match_either_stays_unmatched(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    monkeypatch.setattr(library.shutil, "which", lambda name: None)
    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: _fake_resolve_result(None, None))

    path = _touch(tmp_path / "Totally Unknown Movie - A Subtitle (2099).mkv")
    f = library.LocalMediaFile(path=path, kind="video")
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.matched is False
    assert result.action == "wrote"  # filename-only nfo still written
    assert result.note == "filename-only"


def test_embedded_filename_tmdb_id_unaffected_by_full_title_retry(tmp_path, monkeypatch):
    """Regression: an embedded {tmdb-} filename id must still short-circuit
    resolve() entirely, regardless of subtitle content in the title."""
    monkeypatch.setattr(library, "_guessit", None)
    monkeypatch.setattr(library.shutil, "which", lambda name: None)

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: (_ for _ in ()).throw(
                            AssertionError("resolve() must not be called")))
    monkeypatch.setattr(library, "enrich",
                        lambda seed, **kw: _FakeExpandedExternalIds({}))

    path = _touch(tmp_path / "The Lord of the Rings - The Two Towers (2002) {tmdb-121}.mkv")
    f = library.LocalMediaFile(path=path, kind="video")
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.matched is True
    assert result.external_ids == {"tmdb_movie": 121}


# ---------------------------------------------------------------------------
# tag_library() end-to-end (mocked resolve)
# ---------------------------------------------------------------------------

def test_tag_library_scans_and_tags_a_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    monkeypatch.setattr(library, "_mutagen", None)
    _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    _touch(tmp_path / "Aphex Twin - Avril 14th.mp3")

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: _fake_resolve_result(None, None))
    results = library.tag_library(str(tmp_path), dry_run=False)

    assert len(results) == 2
    assert all(r.action == "wrote" for r in results)
    assert (tmp_path / "Big Buck Bunny (2008).nfo").exists()
    assert (tmp_path / "Aphex Twin - Avril 14th.nfo").exists()


def test_tag_library_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    _touch(tmp_path / "Big Buck Bunny (2008).mp4")

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: _fake_resolve_result(None, None))
    results = library.tag_library(str(tmp_path), dry_run=True)

    assert results[0].action == "would-write"
    assert not (tmp_path / "Big Buck Bunny (2008).nfo").exists()


def test_tag_library_reports_skipped_extras_in_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    _touch(tmp_path / "Trailers" / "x-trailer.mkv")
    _touch(tmp_path / "Movie (2020).mkv")
    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: _fake_resolve_result(None, None))

    stats: dict = {}
    results = library.tag_library(str(tmp_path), dry_run=True, stats=stats)
    assert len(results) == 1
    assert stats["skipped_extras"] == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_tag_library_dry_run(tmp_path, monkeypatch, capsys):
    from metadatarr import cli

    monkeypatch.setattr(library, "_guessit", None)
    _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: _fake_resolve_result(None, None))

    rc = cli.main(["tag-library", "-p", str(tmp_path), "--dry-run"])
    out = capsys.readouterr()
    assert rc == 0
    assert "would-write" in out.out
    assert "scanned=1" in out.out
    assert not (tmp_path / "Big Buck Bunny (2008).nfo").exists()


def test_cli_tag_library_real_run_writes_nfo(tmp_path, monkeypatch, capsys):
    from metadatarr import cli

    monkeypatch.setattr(library, "_guessit", None)
    _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: _fake_resolve_result(None, None))

    rc = cli.main(["tag-library", "-p", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "Big Buck Bunny (2008).nfo").exists()


# ---------------------------------------------------------------------------
# --rename (opt-in, safety-first)
# ---------------------------------------------------------------------------

def _match_resolve(title, year, ids):
    def fake_resolve(signals, *, max_workers=8):
        merged = Signals(title=title, year=year, medium=MediaType.MOVIE)
        return _fake_resolve_result(merged, _FakeExternalIds(ids))
    return fake_resolve


def test_rename_off_by_default_leaves_file(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Inception 2010.mkv", b"data")
    f = library.LocalMediaFile(path=path, kind="video")
    monkeypatch.setattr(library, "resolve", _match_resolve("Inception", 2010, {"tmdb_movie": 27205}))
    result = library.tag_file(f, write_nfo=True, dry_run=False)
    assert result.rename_action == "off"
    assert path.exists()  # untouched


def test_rename_dry_run_previews_and_moves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Inception 2010.mkv", b"data")
    f = library.LocalMediaFile(path=path, kind="video")
    monkeypatch.setattr(library, "resolve", _match_resolve("Inception", 2010, {"tmdb_movie": 27205}))
    result = library.tag_file(f, write_nfo=True, dry_run=True, rename=True)
    assert result.rename_action == "would-rename"
    assert result.renamed_to.name == "Inception (2010) {tmdb-27205}.mkv"
    assert path.exists()  # nothing moved
    assert not result.renamed_to.exists()


def test_rename_real_moves_file_and_syncs_nfo(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Inception 2010.mkv", b"videobytes")
    f = library.LocalMediaFile(path=path, kind="video")
    monkeypatch.setattr(library, "resolve", _match_resolve("Inception", 2010, {"tmdb_movie": 27205}))
    result = library.tag_file(f, write_nfo=True, dry_run=False, rename=True)
    assert result.rename_action == "renamed"
    target = tmp_path / "Inception (2010) {tmdb-27205}.mkv"
    assert target.exists()
    assert target.read_bytes() == b"videobytes"   # content byte-identical
    assert not path.exists()                        # original name gone
    assert (tmp_path / "Inception (2010) {tmdb-27205}.nfo").exists()  # nfo synced


def test_rename_skips_unmatched(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Zzq Unknown Nonsense Xyz.mkv", b"x")
    f = library.LocalMediaFile(path=path, kind="video")
    # resolve yields no ids -> not a confident match
    monkeypatch.setattr(library, "resolve", _match_resolve("Zzq Unknown Nonsense Xyz", None, {}))
    result = library.tag_file(f, write_nfo=True, dry_run=False, rename=True)
    assert result.matched is False
    assert result.rename_action == "skipped-unmatched"
    assert path.exists()  # never renames what it couldn't identify


def test_rename_collision_safe_when_target_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Inception 2010.mkv", b"orig")
    _touch(tmp_path / "Inception (2010) {tmdb-27205}.mkv", b"pre-existing")  # occupy the target
    f = library.LocalMediaFile(path=path, kind="video")
    monkeypatch.setattr(library, "resolve", _match_resolve("Inception", 2010, {"tmdb_movie": 27205}))
    result = library.tag_file(f, write_nfo=True, dry_run=False, rename=True)
    assert result.rename_action == "skipped-exists"
    assert path.exists() and path.read_bytes() == b"orig"          # original intact
    assert (tmp_path / "Inception (2010) {tmdb-27205}.mkv").read_bytes() == b"pre-existing"  # not clobbered


def test_music_falls_back_to_audio_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_mutagen", None)
    path = _touch(tmp_path / "unknown-track.mp3", b"audio")
    f = library.LocalMediaFile(path=path, kind="music")
    # normal resolve yields no ids -> not matched by tags/filename
    monkeypatch.setattr(library, "resolve",
                        lambda signals, *, max_workers=8: _fake_resolve_result(signals, _FakeExternalIds({})))
    import metadatarr.identify as identify_mod
    def fake_identify(src, **kw):
        return SimpleNamespace(
            matched=True,
            signals=Signals(title="Real Song", artist="Real Artist", medium=MediaType.MUSIC),
            external_ids=_FakeExternalIds({"musicbrainz_recording": "mbid-123"}))
    monkeypatch.setattr(identify_mod, "identify_audio", fake_identify)
    result = library.tag_file(f, write_nfo=True, dry_run=False)
    assert result.matched is True
    assert result.note == "matched (audio fingerprint)"
    assert result.external_ids == {"musicbrainz_recording": "mbid-123"}


def test_music_fingerprint_unavailable_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_mutagen", None)
    path = _touch(tmp_path / "unknown-track.mp3", b"audio")
    f = library.LocalMediaFile(path=path, kind="music")
    monkeypatch.setattr(library, "resolve",
                        lambda signals, *, max_workers=8: _fake_resolve_result(signals, _FakeExternalIds({})))
    import metadatarr.identify as identify_mod
    def boom(src, **kw):
        raise RuntimeError("xazam not installed")
    monkeypatch.setattr(identify_mod, "identify_audio", boom)
    result = library.tag_file(f, write_nfo=True, dry_run=False)
    assert result.matched is False  # degraded, no crash


# ---------------------------------------------------------------------------
# tag_file() — YouTube video id (yt-dlp/TubeArchivist/tubesync filenames)
# ---------------------------------------------------------------------------

def test_tag_file_matches_youtube_id_when_no_catalog_id(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Some Talk [dQw4w9WgXcQ].mp4")
    f = library.LocalMediaFile(path=path, kind="video")

    resolve_calls = []

    def fake_resolve(signals, *, max_workers=8):
        resolve_calls.append(signals)
        raise AssertionError("resolve() must not be called when a youtube id is present")

    monkeypatch.setattr(library, "resolve", fake_resolve)
    monkeypatch.setattr(library, "_enrich_from_tutubo", lambda vid: None)

    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert not resolve_calls
    assert result.matched is True
    assert result.note == "matched (youtube id)"
    assert result.external_ids == {"extra": {"youtube": "dQw4w9WgXcQ"}}
    root = ET.fromstring(result.nfo_path.read_text())
    ids = {el.get("type"): el.text for el in root.findall("uniqueid")}
    assert ids.get("youtube") == "dQw4w9WgXcQ"


def test_tag_file_youtube_id_enriched_with_real_title(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "randomjunk [dQw4w9WgXcQ].mp4")
    f = library.LocalMediaFile(path=path, kind="video")

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: (_ for _ in ()).throw(
                            AssertionError("resolve() must not be called")))
    monkeypatch.setattr(
        library, "_enrich_from_tutubo",
        lambda vid: {"title": "Never Gonna Give You Up", "artist": "Rick Astley", "year": 2009},
    )

    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.matched is True
    root = ET.fromstring(result.nfo_path.read_text())
    assert root.findtext("title") == "Never Gonna Give You Up"
    assert root.findtext("studio") == "Rick Astley"
    assert root.findtext("year") == "2009"


def test_tag_file_youtube_enrich_failure_falls_back_to_filename_title(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "My Cool Video [dQw4w9WgXcQ].mp4")
    f = library.LocalMediaFile(path=path, kind="video")

    monkeypatch.setattr(library, "resolve",
                        lambda signals, **kw: (_ for _ in ()).throw(
                            AssertionError("resolve() must not be called")))

    def boom(vid):
        raise RuntimeError("network down")

    monkeypatch.setattr(library, "_enrich_from_tutubo", boom)

    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.matched is True
    assert result.note == "matched (youtube id)"
    root = ET.fromstring(result.nfo_path.read_text())
    # Enrichment failed -> falls back to the filename-derived title (the
    # regex parser doesn't strip a trailing "[VIDEOID]" bracket, only known
    # release-junk tokens) — the important thing is it degrades, not crashes.
    assert root.findtext("title") == "My Cool Video [dQw4w9WgXcQ]"
    ids = {el.get("type"): el.text for el in root.findall("uniqueid")}
    assert ids.get("youtube") == "dQw4w9WgXcQ"


def test_tag_file_tmdb_id_wins_over_youtube_id(tmp_path, monkeypatch):
    """Precedence: a Radarr {tmdb-} id always wins over a youtube id, even
    when the filename also carries a bracketed 11-char youtube-id-shaped
    token."""
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Movie (2020) {tmdb-27205} [dQw4w9WgXcQ].mkv")
    f = library.LocalMediaFile(path=path, kind="video")

    def fake_enrich(seed, *, medium=None, apply_maps=True, max_workers=8):
        return _FakeExpandedExternalIds({"tmdb_movie": 27205})

    monkeypatch.setattr(library, "enrich", fake_enrich)
    monkeypatch.setattr(
        library, "_enrich_from_tutubo",
        lambda vid: (_ for _ in ()).throw(
            AssertionError("tutubo enrich must not run when a catalog id wins")),
    )

    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.matched is True
    assert result.note == "matched (embedded id)"
    assert result.external_ids == {"tmdb_movie": 27205}


# ---------------------------------------------------------------------------
# --incremental / --force
# ---------------------------------------------------------------------------

def test_tag_file_incremental_skips_when_nfo_exists_without_resolving(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    nfo_path = path.with_suffix(".nfo")
    nfo_path.write_text("<movie><title>stale</title></movie>", encoding="utf-8")
    f = library.LocalMediaFile(path=path, kind="video")

    def must_not_resolve(signals, *, max_workers=8):
        raise AssertionError("resolve() must not be called for an incremental skip")

    monkeypatch.setattr(library, "resolve", must_not_resolve)
    result = library.tag_file(f, write_nfo=True, dry_run=False, incremental=True)

    assert result.action == "skipped"
    assert "already tagged" in result.note
    # existing (stale) nfo content is left untouched — proves no write happened.
    assert nfo_path.read_text() == "<movie><title>stale</title></movie>"


def test_tag_file_incremental_tags_normally_when_no_nfo_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    f = library.LocalMediaFile(path=path, kind="video")

    def fake_resolve(signals, *, max_workers=8):
        merged = Signals(title="Big Buck Bunny", year=2008, medium=MediaType.MOVIE)
        return _fake_resolve_result(merged, _FakeExternalIds({"imdb": "tt1254207"}))

    monkeypatch.setattr(library, "resolve", fake_resolve)
    result = library.tag_file(f, write_nfo=True, dry_run=False, incremental=True)

    assert result.action == "wrote"
    assert result.matched is True
    assert path.with_suffix(".nfo").exists()


def test_tag_file_force_retags_even_when_nfo_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    nfo_path = path.with_suffix(".nfo")
    nfo_path.write_text("<movie><title>stale</title></movie>", encoding="utf-8")
    f = library.LocalMediaFile(path=path, kind="video")

    calls = {"n": 0}

    def fake_resolve(signals, *, max_workers=8):
        calls["n"] += 1
        merged = Signals(title="Big Buck Bunny", year=2008, medium=MediaType.MOVIE)
        return _fake_resolve_result(merged, _FakeExternalIds({"imdb": "tt1254207"}))

    monkeypatch.setattr(library, "resolve", fake_resolve)
    result = library.tag_file(
        f, write_nfo=True, dry_run=False, incremental=True, force=True,
    )

    assert calls["n"] == 1
    assert result.action == "wrote"
    root = ET.fromstring(nfo_path.read_text())
    assert root.findtext("title") == "Big Buck Bunny"


def test_tag_file_incremental_with_rename_treats_already_id_tagged_name_as_done(
    tmp_path, monkeypatch,
):
    """With --rename, a file already carrying an embedded {tmdb-id} — the
    rename-target marker — plus its .nfo is considered fully done and
    skipped without resolving."""
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Big Buck Bunny (2008) {tmdb-5431}.mp4")
    path.with_suffix(".nfo").write_text("<movie/>", encoding="utf-8")
    f = library.LocalMediaFile(path=path, kind="video")

    def must_not_resolve(signals, *, max_workers=8):
        raise AssertionError("resolve() must not be called for an incremental skip")

    monkeypatch.setattr(library, "resolve", must_not_resolve)
    result = library.tag_file(
        f, write_nfo=True, dry_run=False, incremental=True, rename=True,
    )

    assert result.action == "skipped"
    assert "already tagged" in result.note
    assert result.rename_action == "skipped-exists"


def test_tag_file_incremental_with_rename_still_tags_when_name_lacks_id(
    tmp_path, monkeypatch,
):
    """With --rename, an nfo existing is not enough on its own — the
    filename must also already carry the embedded id, otherwise the file
    still needs (re)processing."""
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    path.with_suffix(".nfo").write_text("<movie/>", encoding="utf-8")
    f = library.LocalMediaFile(path=path, kind="video")

    def fake_resolve(signals, *, max_workers=8):
        merged = Signals(title="Big Buck Bunny", year=2008, medium=MediaType.MOVIE)
        return _fake_resolve_result(merged, _FakeExternalIds({"tmdb_movie": 5431}))

    monkeypatch.setattr(library, "resolve", fake_resolve)
    result = library.tag_file(
        f, write_nfo=True, dry_run=False, incremental=True, rename=True,
    )

    assert result.action == "wrote"
    assert result.matched is True


def test_tag_library_summary_counts_skipped_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_guessit", None)
    tagged = _touch(tmp_path / "Already Tagged (2001).mkv")
    tagged.with_suffix(".nfo").write_text("<movie/>", encoding="utf-8")
    fresh = _touch(tmp_path / "Fresh Movie (2002).mkv")

    def fake_resolve(signals, *, max_workers=8):
        return _fake_resolve_result(None, None)

    monkeypatch.setattr(library, "resolve", fake_resolve)
    stats: dict = {}
    results = library.tag_library(str(tmp_path), incremental=True, stats=stats)

    assert len(results) == 2
    assert stats.get("skipped_existing") == 1
    by_path = {r.path: r for r in results}
    assert by_path[tagged].note == "already tagged (incremental)"
    assert by_path[fresh].action == "wrote"


def test_tag_file_default_no_incremental_overwrites_existing_nfo(tmp_path, monkeypatch):
    """Unchanged default behaviour: without --incremental, an existing .nfo
    is simply overwritten, resolve() still runs."""
    monkeypatch.setattr(library, "_guessit", None)
    path = _touch(tmp_path / "Big Buck Bunny (2008).mp4")
    nfo_path = path.with_suffix(".nfo")
    nfo_path.write_text("<movie><title>stale</title></movie>", encoding="utf-8")
    f = library.LocalMediaFile(path=path, kind="video")

    def fake_resolve(signals, *, max_workers=8):
        merged = Signals(title="Big Buck Bunny", year=2008, medium=MediaType.MOVIE)
        return _fake_resolve_result(merged, _FakeExternalIds({"imdb": "tt1254207"}))

    monkeypatch.setattr(library, "resolve", fake_resolve)
    result = library.tag_file(f, write_nfo=True, dry_run=False)

    assert result.action == "wrote"
    root = ET.fromstring(nfo_path.read_text())
    assert root.findtext("title") == "Big Buck Bunny"
