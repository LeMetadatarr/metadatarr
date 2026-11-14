# SPDX-License-Identifier: Apache-2.0
"""The slice of the TMDB API the TMDB provider uses: movie search and the
choice of the result that best agrees with a title and year."""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict

from metadatarr.transport import make_session

BASE = "https://api.themoviedb.org/3"


class TMDBMovie(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    title: Optional[str] = None
    release_date: Optional[str] = None

    @property
    def year(self) -> Optional[int]:
        if self.release_date and len(self.release_date) >= 4:
            try:
                return int(self.release_date[:4])
            except ValueError:
                return None
        return None


class TMDBClient:
    def __init__(self, api_key: str, session: Any = None) -> None:
        self.api_key = api_key
        self._session = session if session is not None else make_session()

    def _get(self, path: str, **params: Any) -> Optional[dict]:
        if not self.api_key:
            return None
        try:
            r = self._session.get(f"{BASE}{path}", params={**params, "api_key": self.api_key}, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def search_movie(self, query: str, page: int = 1) -> List[TMDBMovie]:
        """``/search/movie`` results in TMDB's relevance order; a result the
        model rejects is skipped."""
        results = (self._get("/search/movie", query=query, page=page) or {}).get("results")
        out = []
        for raw in results if isinstance(results, list) else []:
            try:
                out.append(TMDBMovie.model_validate(raw))
            except Exception:
                continue
        return out

    def best_match(self, title: str, year: Optional[int] = None) -> Optional[Tuple[TMDBMovie, float]]:
        """The ``(movie, confidence)`` pair that best agrees with *title*:

        - exact (case-insensitive) title and a year within 1: 0.95
        - exact title, no or different year: 0.85
        - the title contains the query or the reverse: 0.60
        - anything else: 0.35, the first result winning ties
        """
        results = self.search_movie(title)
        if not results:
            return None
        query = title.lower()
        best, best_confidence = results[0], -1.0
        for movie in results:
            candidate = (movie.title or "").lower()
            if candidate == query:
                close = year and movie.year and abs(year - movie.year) <= 1
                confidence = 0.95 if close else 0.85
            elif query in candidate or candidate in query:
                confidence = 0.60
            else:
                confidence = 0.35
            if confidence > best_confidence:
                best, best_confidence = movie, confidence
        return best, best_confidence
