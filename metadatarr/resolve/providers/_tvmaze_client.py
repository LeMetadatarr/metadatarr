# SPDX-License-Identifier: Apache-2.0
"""The slice of the TVmaze API the TVmaze provider uses: show search and the
lookup of a show by TheTVDB or IMDb id. No key is needed."""
from __future__ import annotations

from typing import Any, List, Optional

from metadatarr.models import TVmazeShow
from metadatarr.transport import make_session

BASE = "https://api.tvmaze.com"


class TVmazeClient:
    def __init__(self) -> None:
        self._session = make_session()
        self._session.headers["Accept"] = "application/json"

    def _get(self, path: str, **params: Any) -> Any:
        """The decoded JSON body; ``None`` on a failed request (a 404 included)
        or a body that is not JSON."""
        try:
            r = self._session.get(f"{BASE}{path}", params=params or None, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def search_shows(self, query: str) -> List[TVmazeShow]:
        """Shows matching *query*, best first. Raises ``ValidationError`` for a
        show the model rejects."""
        data = self._get("/search/shows", q=query)
        if not isinstance(data, list):
            return []
        return [TVmazeShow.model_validate(item["show"])
                for item in data if isinstance(item, dict) and "show" in item]

    def _lookup(self, **params: Any) -> Optional[TVmazeShow]:
        data = self._get("/lookup/shows", **params)
        return TVmazeShow.model_validate(data) if isinstance(data, dict) else None

    def lookup_by_thetvdb(self, thetvdb_id: int) -> Optional[TVmazeShow]:
        return self._lookup(thetvdb=thetvdb_id)

    def lookup_by_imdb(self, imdb_id: str) -> Optional[TVmazeShow]:
        return self._lookup(imdb=imdb_id)
