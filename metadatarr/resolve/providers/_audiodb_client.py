# SPDX-License-Identifier: Apache-2.0
"""The slice of TheAudioDB's free API the AudioDB provider uses: track search
and the lookup of an artist, album or track by MusicBrainz id. The free key
``123`` is the public one documented at theaudiodb.com/api_guide.php."""
from __future__ import annotations

from typing import Any, List, Optional

from metadatarr.models import AudioDBAlbum, AudioDBArtist, AudioDBTrack
from metadatarr.transport import make_session

BASE = "https://www.theaudiodb.com/api/v1/json/123"


class AudioDBClient:
    def __init__(self) -> None:
        self._session = make_session()
        self._session.headers["Accept"] = "application/json"

    def _get(self, path: str, **params: Any) -> dict:
        """The decoded JSON object; ``{}`` on a failed request or a body that
        is not a JSON object."""
        try:
            r = self._session.get(f"{BASE}/{path}", params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _rows(self, key: str, path: str, **params: Any) -> list:
        rows = self._get(path, **params).get(key)
        return rows if isinstance(rows, list) else []

    def search_track(self, artist: str, title: str) -> List[AudioDBTrack]:
        return [AudioDBTrack.model_validate(t) for t in self._rows("track", "searchtrack.php", s=artist, t=title)]

    def get_artist_by_mbid(self, mbid: str) -> Optional[AudioDBArtist]:
        rows = self._rows("artists", "artist-mb.php", i=mbid)
        return AudioDBArtist.model_validate(rows[0]) if rows else None

    def get_album_by_mbid(self, mbid: str) -> Optional[AudioDBAlbum]:
        rows = self._rows("album", "album-mb.php", i=mbid)
        return AudioDBAlbum.model_validate(rows[0]) if rows else None

    def get_track_by_mbid(self, mbid: str) -> Optional[AudioDBTrack]:
        rows = self._rows("track", "track-mb.php", i=mbid)
        return AudioDBTrack.model_validate(rows[0]) if rows else None
