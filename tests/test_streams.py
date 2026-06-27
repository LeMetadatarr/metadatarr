"""Tests for ExternalIds.streams and the Stream model."""
import pytest
from mediavocab.models import Stream
from mediavocab.models import ExternalIds


# ---------------------------------------------------------------------------
# Stream model
# ---------------------------------------------------------------------------

class TestStreamModel:
    def test_fields(self):
        s = Stream(platform="soundcloud", url="https://soundcloud.com/x/y", kind="track")
        assert s.platform == "soundcloud"
        assert s.url == "https://soundcloud.com/x/y"
        assert s.kind == "track"
        assert s.id is None

    def test_id_field(self):
        s = Stream(platform="youtube", url="https://www.youtube.com/watch?v=abc",
                   kind="video", id="abc")
        assert s.id == "abc"


# ---------------------------------------------------------------------------
# ExternalIds.streams — playable URL passthrough cases
# ---------------------------------------------------------------------------

class TestStreamsFromUrl:
    def test_soundcloud_track(self):
        ids = ExternalIds(extra={"soundcloud_track_url": "https://soundcloud.com/artist/track"})
        streams = ids.streams
        assert len(streams) == 1
        assert streams[0].platform == "soundcloud"
        assert streams[0].kind == "track"
        assert streams[0].url == "https://soundcloud.com/artist/track"
        assert streams[0].id is None

    def test_bandcamp_track(self):
        ids = ExternalIds(extra={"bandcamp_track_url": "https://artist.bandcamp.com/track/song"})
        streams = ids.streams
        assert len(streams) == 1
        assert streams[0].platform == "bandcamp"
        assert streams[0].kind == "track"

    def test_bandcamp_album(self):
        ids = ExternalIds(extra={"bandcamp_album_url": "https://artist.bandcamp.com/album/record"})
        streams = ids.streams
        assert len(streams) == 1
        assert streams[0].platform == "bandcamp"
        assert streams[0].kind == "album"

    def test_music_video_url(self):
        ids = ExternalIds(extra={"music_video_url": "https://www.youtube.com/watch?v=xyz"})
        streams = ids.streams
        assert len(streams) == 1
        assert streams[0].platform == "youtube"
        assert streams[0].kind == "video"
        assert streams[0].id is None   # passthrough, no template

    def test_radio_stream(self):
        ids = ExternalIds(extra={"stream_url": "https://radio.example.com/stream.aac"})
        streams = ids.streams
        assert len(streams) == 1
        assert streams[0].platform == "radio"
        assert streams[0].kind == "stream"
        assert streams[0].url == "https://radio.example.com/stream.aac"


# ---------------------------------------------------------------------------
# ExternalIds.streams — ID → URL construction cases
# ---------------------------------------------------------------------------

class TestStreamsFromId:
    def test_youtube_video_id(self):
        ids = ExternalIds(extra={"youtube_video_id": "dQw4w9WgXcQ"})
        streams = ids.streams
        assert len(streams) == 1
        assert streams[0].platform == "youtube"
        assert streams[0].url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert streams[0].id == "dQw4w9WgXcQ"

    def test_youtube_music_video_id(self):
        ids = ExternalIds(extra={"youtube_music_video_id": "abc123"})
        streams = ids.streams
        assert len(streams) == 1
        assert streams[0].platform == "youtube_music"
        assert streams[0].url == "https://music.youtube.com/watch?v=abc123"
        assert streams[0].id == "abc123"

    def test_youtube_music_playlist_id(self):
        ids = ExternalIds(extra={"youtube_music_playlist_id": "PLxxx"})
        streams = ids.streams
        assert len(streams) == 1
        assert streams[0].platform == "youtube_music"
        assert streams[0].kind == "playlist"
        assert streams[0].url == "https://music.youtube.com/playlist?list=PLxxx"
        assert streams[0].id == "PLxxx"


# ---------------------------------------------------------------------------
# Non-playable keys — must NOT appear in streams
# ---------------------------------------------------------------------------

class TestStreamsExclusions:
    def test_soundcloud_artist_url_excluded(self):
        ids = ExternalIds(extra={"soundcloud_artist_url": "https://soundcloud.com/artist"})
        assert ids.streams == []

    def test_bandcamp_artist_url_excluded(self):
        ids = ExternalIds(extra={"bandcamp_artist_url": "https://artist.bandcamp.com"})
        assert ids.streams == []

    def test_youtube_channel_id_excluded(self):
        ids = ExternalIds(extra={"youtube_channel_id": "UCxxxxxx"})
        assert ids.streams == []

    def test_youtube_music_artist_browse_id_excluded(self):
        ids = ExternalIds(extra={"youtube_music_artist_browse_id": "MPLAxxx"})
        assert ids.streams == []

    def test_empty_extra(self):
        assert ExternalIds().streams == []

    def test_unrelated_extra_key(self):
        ids = ExternalIds(extra={"dvdcompare_url": "https://dvdcompare.net/x"})
        assert ids.streams == []


# ---------------------------------------------------------------------------
# Multiple streams
# ---------------------------------------------------------------------------

class TestMultipleStreams:
    def test_two_platforms(self):
        ids = ExternalIds(extra={
            "soundcloud_track_url": "https://soundcloud.com/a/b",
            "bandcamp_track_url":   "https://x.bandcamp.com/track/y",
        })
        streams = ids.streams
        assert len(streams) == 2
        platforms = {s.platform for s in streams}
        assert platforms == {"soundcloud", "bandcamp"}

    def test_order_matches_stream_map(self):
        ids = ExternalIds(extra={
            "youtube_video_id":    "vid1",
            "soundcloud_track_url": "https://soundcloud.com/a/b",
        })
        streams = ids.streams
        assert len(streams) == 2
        # soundcloud comes before youtube in _STREAM_MAP
        assert streams[0].platform == "soundcloud"
        assert streams[1].platform == "youtube"

    def test_mixed_url_and_id(self):
        ids = ExternalIds(extra={
            "bandcamp_track_url":  "https://x.bandcamp.com/track/y",
            "youtube_video_id":    "dQw4w9WgXcQ",
        })
        streams = ids.streams
        bc = next(s for s in streams if s.platform == "bandcamp")
        yt = next(s for s in streams if s.platform == "youtube")
        assert bc.id is None
        assert yt.id == "dQw4w9WgXcQ"


# ---------------------------------------------------------------------------
# Mappings round-trip — stream_url survives _load_file → to_external_ids → .streams
# ---------------------------------------------------------------------------

class TestMappingsStreamUrl:
    def test_stream_url_in_url_keys(self):
        from metadatarr.resolve.mappings import _URL_KEYS
        assert "stream_url" in _URL_KEYS

    def test_stream_url_stored_in_extra(self):
        from metadatarr.resolve.mappings import MappingEntry
        from metadatarr.resolve.entities import EntityRole
        entry = MappingEntry(
            role=EntityRole.CHANNEL,
            name="Test Radio",
            identifiers={"stream_url": "https://radio.example.com/live.aac"},
        )
        ids = entry.to_external_ids()
        assert ids.extra.get("stream_url") == "https://radio.example.com/live.aac"

    def test_stream_url_surfaces_in_streams(self):
        from metadatarr.resolve.mappings import MappingEntry
        from metadatarr.resolve.entities import EntityRole
        entry = MappingEntry(
            role=EntityRole.CHANNEL,
            name="Test Radio",
            identifiers={"stream_url": "https://radio.example.com/live.aac"},
        )
        ids = entry.to_external_ids()
        streams = ids.streams
        assert len(streams) == 1
        assert streams[0].platform == "radio"
        assert streams[0].url == "https://radio.example.com/live.aac"
