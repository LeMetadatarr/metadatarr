import logging
import os
import re
import requests
from typing import Dict, List, Optional, Union

LOG = logging.getLogger("metadatarr.client")
from .models import (
    SonarrSeries,
    RadarrMovie,
    LidarrArtist,
    AnnasArchiveBook,
    BookInfoSearchHit,
    BookInfoWork,
    BookInfoAuthor,
    OpenLibrarySearchHit,
    OpenLibraryWork,
    OpenLibraryEdition,
    OpenLibraryAuthor,
    AudioDBArtist,
    AudioDBAlbum,
    AudioDBTrack,
    TVmazeShow,
    TVmazePerson,
    TVmazeSeason,
    TVmazeCastMember,
    BlurayComSearchHit,
    BlurayComEdition,
    BlurayComAudioTrack,
    CutRuntime,
    DVDCompareEdition,
    DVDCompareRelease,
    DiscogsSearchHit,
    DiscogsRelease,
    DiscogsIdentifier,
    DiscogsFormatDetail,
    DiscogsCommunity,
)
from bs4 import BeautifulSoup
from urllib.parse import quote_plus


class ArrMetadataClient:
    """
    A client to query the Servarr metadata proxy servers (Skyhook/MusicInfo).
    """

    def __init__(self, user_agent: str = "ArrMetadataClient/1.0"):
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "application/json"
        }

        self.endpoints = {
            "sonarr": "https://skyhook.sonarr.tv/v1",
            "radarr": "https://radarrapi.servarr.com/v1",
            "lidarr": "https://api.lidarr.audio/api/v0.4"
        }

    def _get(self, url: str, params: Optional[Dict] = None) -> Union[Dict, List]:
        """Internal helper to execute the GET request."""
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            LOG.warning("ArrMetadataClient request failed for %s: %s", url, e)
            return [] if "search" in url else {}

    # --- SONARR (TV) ---

    def search_series(self, term: str) -> List[SonarrSeries]:
        url = f"{self.endpoints['sonarr']}/tvdb/search/en/"
        data = self._get(url, params={"term": term})
        return [SonarrSeries.model_validate(item) for item in data] if isinstance(data, list) else []

    def get_series_info(self, tvdb_id: Union[int, str]) -> Optional[SonarrSeries]:
        url = f"{self.endpoints['sonarr']}/tvdb/shows/en/{tvdb_id}"
        data = self._get(url)
        return SonarrSeries.model_validate(data) if data else None

    # --- RADARR (Movies) ---

    def search_movie(self, term: str) -> List[RadarrMovie]:
        url = f"{self.endpoints['radarr']}/search"
        data = self._get(url, params={"q": term})
        return [RadarrMovie.model_validate(item) for item in data] if isinstance(data, list) else []

    def get_movie_info(self, tmdb_id: Union[int, str]) -> Optional[RadarrMovie]:
        url = f"{self.endpoints['radarr']}/movie/{tmdb_id}"
        data = self._get(url)
        return RadarrMovie.model_validate(data) if data else None

    # --- LIDARR (Music) ---

    def search_artist(self, term: str) -> List[LidarrArtist]:
        url = f"{self.endpoints['lidarr']}/search"
        data = self._get(url, params={"query": term, "type": "artist"})
        return [LidarrArtist.model_validate(item) for item in data] if isinstance(data, list) else []

    def get_artist_info(self, mbid: str) -> Optional[LidarrArtist]:
        url = f"{self.endpoints['lidarr']}/artist/{mbid}"
        data = self._get(url)
        return LidarrArtist.model_validate(data) if data else None


class BookInfoClient:
    """
    Client for rreading-glasses metadata proxies (https://github.com/blampe/rreading-glasses).

    Two hosted instances are available:
      - https://api.bookinfo.pro       (Goodreads-backed)
      - https://hardcover.bookinfo.pro (Hardcover-backed)

    Endpoints:
      GET /search?q=<term>   -> list[{bookId, workId, author:{id}}]
      GET /work/{id}         -> work payload (with editions in Books)
      GET /book/{id}         -> work payload for the work containing this edition
      GET /author/{id}       -> author payload
    """

    GOODREADS = "https://api.bookinfo.pro"
    HARDCOVER = "https://hardcover.bookinfo.pro"

    def __init__(self, base_url: str = GOODREADS, user_agent: str = "metadatarr/0.1.0", timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}

    @classmethod
    def goodreads(cls, **kwargs) -> "BookInfoClient":
        return cls(base_url=cls.GOODREADS, **kwargs)

    @classmethod
    def hardcover(cls, **kwargs) -> "BookInfoClient":
        return cls(base_url=cls.HARDCOVER, **kwargs)

    def _get(self, path: str, params: Optional[Dict] = None) -> Union[Dict, List, None]:
        try:
            r = requests.get(f"{self.base_url}{path}", headers=self.headers, params=params, timeout=self.timeout)
            r.raise_for_status()
            if not r.content:
                return None
            return r.json()
        except Exception:
            return None

    def search(self, query: str) -> List[BookInfoSearchHit]:
        data = self._get("/search", params={"q": query})
        if not isinstance(data, list):
            return []
        return [BookInfoSearchHit.model_validate(item) for item in data]

    def get_work(self, work_id: Union[int, str]) -> Optional[BookInfoWork]:
        data = self._get(f"/work/{work_id}")
        return BookInfoWork.model_validate(data) if isinstance(data, dict) else None

    def get_book(self, book_id: Union[int, str]) -> Optional[BookInfoWork]:
        data = self._get(f"/book/{book_id}")
        return BookInfoWork.model_validate(data) if isinstance(data, dict) else None

    def get_author(self, author_id: Union[int, str]) -> Optional[BookInfoAuthor]:
        data = self._get(f"/author/{author_id}")
        return BookInfoAuthor.model_validate(data) if isinstance(data, dict) else None


class OpenLibraryClient:
    """
    Client for the OpenLibrary REST API (https://openlibrary.org/developers/api).

    Endpoints used:
      GET /search.json?q=<term>     -> {numFound, docs:[...]}
      GET /works/{OLID}.json        -> work payload
      GET /books/{OLID}.json        -> edition payload
      GET /authors/{OLID}.json      -> author payload
      GET /isbn/{isbn}.json         -> edition payload (resolved by ISBN)

    Cover image URLs follow:
      https://covers.openlibrary.org/b/id/{cover_id}-{S|M|L}.jpg
    """

    BASE_URL = "https://openlibrary.org"
    COVERS_URL = "https://covers.openlibrary.org"

    def __init__(self, base_url: str = BASE_URL, user_agent: str = "metadatarr/0.1.0", timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}

    def _get(self, path: str, params: Optional[Dict] = None) -> Optional[Union[Dict, List]]:
        try:
            r = requests.get(f"{self.base_url}{path}", headers=self.headers, params=params, timeout=self.timeout)
            r.raise_for_status()
            return r.json() if r.content else None
        except Exception:
            return None

    def search(self, query: str, limit: int = 10) -> List[OpenLibrarySearchHit]:
        data = self._get("/search.json", params={"q": query, "limit": limit})
        if not isinstance(data, dict):
            return []
        docs = data.get("docs", []) or []
        return [OpenLibrarySearchHit.model_validate(d) for d in docs]

    def get_work(self, work_id: str) -> Optional[OpenLibraryWork]:
        work_id = work_id.strip("/").split("/")[-1]
        data = self._get(f"/works/{work_id}.json")
        return OpenLibraryWork.from_api(data) if isinstance(data, dict) else None

    def get_edition(self, edition_id: str) -> Optional[OpenLibraryEdition]:
        edition_id = edition_id.strip("/").split("/")[-1]
        data = self._get(f"/books/{edition_id}.json")
        return OpenLibraryEdition.from_api(data) if isinstance(data, dict) else None

    def get_edition_by_isbn(self, isbn: str) -> Optional[OpenLibraryEdition]:
        data = self._get(f"/isbn/{isbn}.json")
        return OpenLibraryEdition.from_api(data) if isinstance(data, dict) else None

    def get_author(self, author_id: str) -> Optional[OpenLibraryAuthor]:
        author_id = author_id.strip("/").split("/")[-1]
        data = self._get(f"/authors/{author_id}.json")
        return OpenLibraryAuthor.from_api(data) if isinstance(data, dict) else None

    @classmethod
    def cover_url(cls, cover_id: int, size: str = "L") -> str:
        size = size.upper() if size.upper() in {"S", "M", "L"} else "L"
        return f"{cls.COVERS_URL}/b/id/{cover_id}-{size}.jpg"


class AnnasArchiveClient:
    """
    A client to query Anna's Archive mirrors.
    """
    DEFAULT_MIRRORS = [
        'https://annas-archive.se',
        'https://annas-archive.li',
        'https://annas-archive.pm',
        'https://annas-archive.in',
        'https://annas-archive.gl',
        'https://annas-archive.pk',
        'https://annas-archive.vg',
        'https://annas-archive.gd'
    ]

    def __init__(self, mirrors: Optional[List[str]] = None, user_agent: str = "metadatarr/0.1.0"):
        self.mirrors = mirrors or self.DEFAULT_MIRRORS
        self.working_mirror = None
        self.headers = {
            "User-Agent": user_agent
        }

    def search(self, query: str, timeout: int = 15) -> List[AnnasArchiveBook]:
        """Search for books across mirrors and parse HTML results."""
        mirrors = list(self.mirrors)
        for mirror in mirrors:
            try:
                search_url = f"{mirror}/search?q={quote_plus(query)}&display=table"
                response = requests.get(search_url, headers=self.headers, timeout=timeout)
                if 200 <= response.status_code < 300:
                    self.working_mirror = mirror
                    return self._parse_search_results(response.text)
            except Exception:
                continue
        
        return []

    def _parse_search_results(self, html_content: str) -> List[AnnasArchiveBook]:
        soup = BeautifulSoup(html_content, "html.parser")
        books = []
        
        table = soup.find('table')
        if not table:
            return []
            
        rows = table.find_all('tr')
        for row in rows:
            columns = row.find_all("td")
            if not columns or len(columns) < 10:
                continue

            cover_link = columns[0].find('a', tabindex="-1")
            if not cover_link:
                continue
            
            href = cover_link.get('href', '')
            md5 = href.split('/')[-1] if href else ""
            if not md5:
                continue

            title = columns[1].get_text(strip=True)
            author = columns[2].get_text(strip=True)
            formats = columns[9].get_text(strip=True).upper()
            
            img = columns[0].find('img')
            cover_url = img.get('src', '') if img else ''
            
            language = columns[3].get_text(strip=True)
            size = columns[8].get_text(strip=True)

            if title and author:
                books.append(AnnasArchiveBook(
                    title=title,
                    author=author,
                    formats=formats,
                    md5=md5,
                    cover_url=cover_url,
                    language=language,
                    size=size
                ))
        
        return books


class AudioDBClient:
    """Client for TheAudioDB free API (key=123).

    All endpoints are read-only and require no authentication.  The free key
    ``123`` is the public key documented at theaudiodb.com/api_guide.php.
    """

    BASE = "https://www.theaudiodb.com/api/v1/json/123"

    def __init__(self, user_agent: str = "metadatarr/1.0"):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._session.headers["Accept"] = "application/json"

    def _get(self, path: str, **params) -> dict:
        try:
            r = self._session.get(f"{self.BASE}/{path}", params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Artist
    # ------------------------------------------------------------------

    def search_artist(self, name: str) -> List[AudioDBArtist]:
        data = self._get("search.php", s=name)
        return [AudioDBArtist.model_validate(a) for a in (data.get("artists") or [])]

    def get_artist(self, audiodb_id: str) -> Optional[AudioDBArtist]:
        data = self._get("artist.php", i=audiodb_id)
        artists = data.get("artists") or []
        return AudioDBArtist.model_validate(artists[0]) if artists else None

    def get_artist_by_mbid(self, mbid: str) -> Optional[AudioDBArtist]:
        data = self._get("artist-mb.php", i=mbid)
        artists = data.get("artists") or []
        return AudioDBArtist.model_validate(artists[0]) if artists else None

    # ------------------------------------------------------------------
    # Album
    # ------------------------------------------------------------------

    def search_album(self, artist: str, album: Optional[str] = None) -> List[AudioDBAlbum]:
        params = {"s": artist}
        if album:
            params["a"] = album
        data = self._get("searchalbum.php", **params)
        return [AudioDBAlbum.model_validate(a) for a in (data.get("album") or [])]

    def get_album(self, audiodb_id: str) -> Optional[AudioDBAlbum]:
        data = self._get("album.php", i=audiodb_id)
        albums = data.get("album") or []
        return AudioDBAlbum.model_validate(albums[0]) if albums else None

    def get_album_by_mbid(self, mbid: str) -> Optional[AudioDBAlbum]:
        data = self._get("album-mb.php", i=mbid)
        albums = data.get("album") or []
        return AudioDBAlbum.model_validate(albums[0]) if albums else None

    def discography(self, artist: str) -> List[AudioDBAlbum]:
        """Lightweight discography — returns album name + year only (free tier)."""
        data = self._get("discography.php", s=artist)
        out = []
        for raw in data.get("album") or []:
            try:
                out.append(AudioDBAlbum.model_validate(raw))
            except Exception:
                pass
        return out

    # ------------------------------------------------------------------
    # Track
    # ------------------------------------------------------------------

    def search_track(self, artist: str, title: str) -> List[AudioDBTrack]:
        data = self._get("searchtrack.php", s=artist, t=title)
        return [AudioDBTrack.model_validate(t) for t in (data.get("track") or [])]

    def get_track(self, audiodb_id: str) -> Optional[AudioDBTrack]:
        data = self._get("track.php", h=audiodb_id)
        tracks = data.get("track") or []
        return AudioDBTrack.model_validate(tracks[0]) if tracks else None

    def get_track_by_mbid(self, mbid: str) -> Optional[AudioDBTrack]:
        data = self._get("track-mb.php", i=mbid)
        tracks = data.get("track") or []
        return AudioDBTrack.model_validate(tracks[0]) if tracks else None


class TVmazeClient:
    """Client for the TVmaze public API (https://www.tvmaze.com/api).

    No authentication or API key required.  Rate limit is 20 requests per 10
    seconds for unauthenticated clients.
    """

    BASE = "https://api.tvmaze.com"

    def __init__(self, user_agent: str = "metadatarr/1.0"):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._session.headers["Accept"] = "application/json"

    def _get(self, path: str, **params) -> Optional[Union[Dict, List]]:
        try:
            r = self._session.get(f"{self.BASE}{path}", params=params or None, timeout=10)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Show search & lookup
    # ------------------------------------------------------------------

    def search_shows(self, query: str) -> List[TVmazeShow]:
        data = self._get("/search/shows", q=query)
        if not isinstance(data, list):
            return []
        return [TVmazeShow.model_validate(item["show"]) for item in data if "show" in item]

    def singlesearch(self, query: str) -> Optional[TVmazeShow]:
        data = self._get("/singlesearch/shows", q=query)
        return TVmazeShow.model_validate(data) if isinstance(data, dict) else None

    def get_show(self, tvmaze_id: int) -> Optional[TVmazeShow]:
        data = self._get(f"/shows/{tvmaze_id}")
        return TVmazeShow.model_validate(data) if isinstance(data, dict) else None

    def lookup_by_thetvdb(self, thetvdb_id: int) -> Optional[TVmazeShow]:
        data = self._get("/lookup/shows", thetvdb=thetvdb_id)
        return TVmazeShow.model_validate(data) if isinstance(data, dict) else None

    def lookup_by_imdb(self, imdb_id: str) -> Optional[TVmazeShow]:
        data = self._get("/lookup/shows", imdb=imdb_id)
        return TVmazeShow.model_validate(data) if isinstance(data, dict) else None

    # ------------------------------------------------------------------
    # Seasons & cast
    # ------------------------------------------------------------------

    def get_seasons(self, tvmaze_id: int) -> List[TVmazeSeason]:
        data = self._get(f"/shows/{tvmaze_id}/seasons")
        if not isinstance(data, list):
            return []
        return [TVmazeSeason.model_validate(s) for s in data]

    def get_cast(self, tvmaze_id: int) -> List[TVmazeCastMember]:
        data = self._get(f"/shows/{tvmaze_id}/cast")
        if not isinstance(data, list):
            return []
        return [TVmazeCastMember.model_validate(m) for m in data]

    # ------------------------------------------------------------------
    # People
    # ------------------------------------------------------------------

    def search_people(self, query: str) -> List[TVmazePerson]:
        data = self._get("/search/people", q=query)
        if not isinstance(data, list):
            return []
        return [TVmazePerson.model_validate(item["person"]) for item in data if "person" in item]


# ---------------------------------------------------------------------------
# Blu-ray.com scraper
# ---------------------------------------------------------------------------

_BLURAY_BASE = "https://www.blu-ray.com"
_BLURAY_ID_RE = re.compile(r"/movies/[^/]+/(\d+)/")


class BlurayComClient:
    """HTML scraper for blu-ray.com.  No API key required."""

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, timeout: int = 15) -> None:
        self._session = requests.Session()
        self._session.headers.update(self._HEADERS)
        self._timeout = timeout

    def _get_html(self, url: str, params: Optional[Dict] = None):
        resp = self._session.get(url, params=params, timeout=self._timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser"), resp.url

    def search(self, title: str) -> List[BlurayComSearchHit]:
        """Search blu-ray.com for physical releases matching *title*.

        .. warning::
            blu-ray.com renders search results client-side via JavaScript.
            This method parses the static HTML fallback, which may return an
            empty list on modern site versions.  For reliable lookup, use
            :meth:`get_edition_by_url` with a known direct URL, or
            :meth:`get_edition` with a known numeric id.
        """
        soup, _ = self._get_html(
            f"{_BLURAY_BASE}/movies/search.php",
            params={"keyword": title, "submit": "Search", "section": "bluraymovies"},
        )
        results: List[BlurayComSearchHit] = []
        # Each result is in a <div> with class "hitsperpage" or a movie-grid item.
        for item in soup.select("div.hitsperpage, div.hitslisting"):
            a_tag = item.select_one("a[href*='/movies/']")
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            m = _BLURAY_ID_RE.search(href)
            if not m:
                continue
            bid = int(m.group(1))
            title_tag = item.select_one("span.hittitle, a.hittitlelink, div.hittitle")
            hit_title = (title_tag.get_text(strip=True) if title_tag else a_tag.get_text(strip=True))
            year_tag = item.select_one("span.hityear, span.year")
            year: Optional[int] = None
            if year_tag:
                try:
                    year = int(re.search(r"\d{4}", year_tag.get_text()).group())
                except Exception:
                    pass
            img = item.select_one("img")
            cover = img.get("src") or img.get("data-src") if img else None
            rating_tag = item.select_one("span.ratingscore, span.rating-score")
            rating: Optional[float] = None
            if rating_tag:
                try:
                    rating = float(rating_tag.get_text(strip=True))
                except Exception:
                    pass
            results.append(BlurayComSearchHit(
                bluray_com_id=bid,
                title=hit_title,
                year=year,
                url=f"{_BLURAY_BASE}{href}" if href.startswith("/") else href,
                cover_url=cover,
                rating=rating,
            ))
        return results

    def get_edition(self, bluray_com_id: int) -> Optional[BlurayComEdition]:
        """Fetch full technical specs for a blu-ray.com movie page."""
        soup, page_url = self._get_html(f"{_BLURAY_BASE}/movies/redirect.php",
                                        params={"id": bluray_com_id})
        return self._parse_edition_page(soup, bluray_com_id, page_url)

    def get_edition_by_url(self, url: str) -> Optional[BlurayComEdition]:
        soup, _ = self._get_html(url)
        m = _BLURAY_ID_RE.search(url)
        bid = int(m.group(1)) if m else 0
        return self._parse_edition_page(soup, bid, url)

    def _parse_edition_page(self, soup: BeautifulSoup, bid: int,
                             url: Optional[str]) -> Optional[BlurayComEdition]:
        # Title: <h1> or page <title> "TITLE Blu-ray (COUNTRY)"
        title_tag = soup.select_one("h1")
        if title_tag:
            title = title_tag.get_text(strip=True)
        elif soup.title:
            raw = soup.title.get_text(strip=True)
            title = re.sub(r"\s+(Blu-ray|4K|DVD|UHD).*$", "", raw, flags=re.I).strip()
        else:
            return None
        if not title or "No such movie" in title:
            return None

        # Year: from meta description "TITLE Blu-ray Release Date Month DD, YYYY"
        year: Optional[int] = None
        desc_tag = soup.find("meta", attrs={"name": "description"})
        if desc_tag:
            m_year = re.search(r"Release Date\s+\w+ \d+,\s+(\d{4})", desc_tag.get("content", ""))
            if m_year:
                year = int(m_year.group(1))
        if not year:
            a_year = soup.find("a", href=re.compile(r"/movies/year/\d{4}"))
            if a_year:
                try:
                    year = int(re.search(r"\d{4}", a_year.get_text()).group())
                except Exception:
                    pass

        # Release date: from meta description
        release_date: Optional[str] = None
        if desc_tag:
            m_rd = re.search(r"Release Date\s+(\w+ \d+, \d{4})", desc_tag.get("content", ""))
            if m_rd:
                release_date = m_rd.group(1)

        # Cover image
        cover_tag = soup.select_one("img.coverfront, img#frontimage_overlay")
        cover_url = cover_tag.get("src") if cover_tag else None

        # ----------------------------------------------------------------
        # Spec block: blu-ray.com puts all specs inside a single
        # <td width="228px" style="font-size: 12px"> as <br>-separated lines.
        # Sections: <span class="subheading">SECTION</span>.
        # Audio in <div id="shortaudio">, subtitles in <div id="shortsubs">.
        # We parse the raw HTML string to handle mixed text/tag nodes cleanly.
        # ----------------------------------------------------------------
        video_codec: Optional[str] = None
        video_bitrate_kbps: Optional[int] = None
        resolution: Optional[str] = None
        aspect_ratio: Optional[str] = None
        original_aspect_ratio: Optional[str] = None
        hdr: Optional[str] = None
        audio_tracks: List[BlurayComAudioTrack] = []
        subtitles: List[str] = []
        disc_format: Optional[str] = None
        disc_count: Optional[int] = None
        disc_type: Optional[str] = None
        bd_live: Optional[bool] = None
        packaging: Optional[str] = None
        region: Optional[str] = None
        genres: List[str] = []

        spec_td = None
        for td in soup.find_all("td"):
            if td.get("width", "") in ("228", "228px") and "Codec" in td.get_text():
                spec_td = td
                break

        if spec_td:
            raw_spec = spec_td.decode_contents()
            # Mark section boundaries, then strip all HTML
            raw_spec = re.sub(
                r'<span[^>]*class="subheading"[^>]*>([^<]+)</span>',
                r"@@SECTION:\1@@", raw_spec, flags=re.I)
            # Drop "long" audio/subs divs (duplicate of short ones)
            raw_spec = re.sub(r'<div id="long[^"]*"[^>]*>.*?</div>', "", raw_spec, flags=re.S)
            raw_spec = re.sub(r"<[^>]+>", "\n", raw_spec)
            raw_spec = raw_spec.replace("&nbsp;", " ").replace("&#160;", " ")

            current_section = "video"
            pending_descriptive = False
            for raw_line in re.split(r"\n+", raw_spec):
                line = raw_line.strip()
                if not line or line in ("less", "more", "(", ")"):
                    continue
                m_sec = re.match(r"@@SECTION:(.+)@@", line)
                if m_sec:
                    current_section = m_sec.group(1).strip().lower()
                    continue

                if current_section == "video":
                    if line.startswith("Codec:"):
                        raw_codec = line[6:].strip()
                        m_bps = re.search(r"\((\d+(?:\.\d+)?)\s*Mbps\)", raw_codec)
                        if m_bps:
                            video_bitrate_kbps = int(float(m_bps.group(1)) * 1000)
                            raw_codec = raw_codec[:m_bps.start()].strip()
                        video_codec = raw_codec
                    elif line.startswith("Resolution:"):
                        resolution = line.split(":", 1)[1].strip()
                    elif re.match(r"Aspect ratio:", line, re.I):
                        aspect_ratio = line.split(":", 1)[1].strip()
                    elif re.match(r"Original aspect ratio:", line, re.I):
                        original_aspect_ratio = line.split(":", 1)[1].strip()
                    elif re.match(r"HDR", line, re.I) and ":" in line:
                        hdr = line.split(":", 1)[1].strip()

                elif current_section == "audio":
                    if re.match(r"Audio\s+[Dd]escriptive", line, re.I):
                        pending_descriptive = True
                        continue
                    # "English: DTS-HD Master Audio 5.1 (48kHz, 24-bit)"
                    if ":" in line:
                        colon = line.index(":")
                        lang = line[:colon].strip()
                        rest = line[colon+1:].strip()
                        # Extract sample rate / bit depth
                        sr: Optional[float] = None
                        bd_bits: Optional[int] = None
                        m_sr = re.search(r"\((\d+(?:\.\d+)?)kHz(?:,\s*(\d+)-bit)?\)", rest)
                        if m_sr:
                            sr = float(m_sr.group(1))
                            bd_bits = int(m_sr.group(2)) if m_sr.group(2) else None
                            rest = rest[:m_sr.start()].strip()
                        # Split codec from channels (last "N.N" token)
                        ch_m = re.search(r"(\d+\.\d+)$", rest)
                        if ch_m:
                            channels_str = ch_m.group(1)
                            codec_only = rest[:ch_m.start()].strip()
                        else:
                            channels_str = None
                            codec_only = rest
                        audio_tracks.append(BlurayComAudioTrack(
                            language=lang,
                            codec=codec_only or None,
                            channels=channels_str,
                            sample_rate_khz=sr,
                            bit_depth=bd_bits,
                            is_descriptive=pending_descriptive,
                        ))
                        pending_descriptive = False

                elif current_section == "subtitles":
                    for s in re.split(r",\s*", line):
                        s = re.sub(r"\s+", " ", s).strip().rstrip("(").strip()
                        if s and s.lower() not in ("less", "more", ""):
                            subtitles.append(s)

                elif current_section == "discs":
                    if re.match(r"Blu-ray|DVD|UHD|4K|HD DVD", line, re.I) and "Disc" in line:
                        disc_format = "Blu-ray" if "Blu-ray" in line else line.split()[0]
                    m_disc = re.search(r"(\d+)\s*(BD-\d+|DVD-\d+|UHD-\d+)", line)
                    if m_disc:
                        disc_count = int(m_disc.group(1))
                        disc_type = m_disc.group(2)
                    if "BD-Live" in line:
                        bd_live = True

                elif current_section == "packaging":
                    if line:
                        packaging = (packaging + ", " + line) if packaging else line

                elif current_section == "playback":
                    m_reg = re.search(r"Region\s+(\w+)", line, re.I)
                    if m_reg:
                        region = m_reg.group(1)

        # Genres: from the appeal divs rendered in the same table row
        for genre_div in soup.select("div.blumovieappeal, div[class*='appeal']"):
            gtxt = genre_div.get_text(strip=True)
            if gtxt and len(gtxt) < 40:
                genres.append(gtxt)
        if not genres:
            for genre_div in soup.select("div[style*='position: relative']"):
                gtxt = genre_div.get_text(strip=True)
                if gtxt and len(gtxt) < 30 and re.match(r"^[A-Za-z &/\-]+$", gtxt):
                    genres.append(gtxt)

        # Community stats: popularity%, collections, fans
        popularity_pct: Optional[int] = None
        collections_count: Optional[int] = None
        fans_count: Optional[int] = None
        full_text = soup.get_text("\n")
        m_pop = re.search(r"(\d+)%\s*popularity", full_text, re.I)
        if m_pop:
            popularity_pct = int(m_pop.group(1))
        m_col = re.search(r"(\d+)\s*collections?", full_text, re.I)
        if m_col:
            collections_count = int(m_col.group(1))
        m_fans = re.search(r"(\d+)\s*fans?", full_text, re.I)
        if m_fans:
            fans_count = int(m_fans.group(1))

        # User ratings (video / audio / extras / overall)
        # They appear in the page as "Video\n0.0\nAudio\n0.0\nExtras\n0.0\nOverall\n0.0"
        ur_video = ur_audio = ur_extras = ur_overall = None
        m_ur = re.search(
            r"Blu-ray user rating\s+Video\s+([\d.]+)\s+Audio\s+([\d.]+)\s+"
            r"Extras\s+([\d.]+)\s+Overall\s+([\d.]+)",
            full_text, re.I)
        if m_ur:
            def _f(s: str) -> Optional[float]:
                try:
                    v = float(s)
                    return v if v > 0 else None
                except Exception:
                    return None
            ur_video = _f(m_ur.group(1))
            ur_audio = _f(m_ur.group(2))
            ur_extras = _f(m_ur.group(3))
            ur_overall = _f(m_ur.group(4))

        # Studio: appears as "By studio  StudioName"
        studio: Optional[str] = None
        m_studio = re.search(r"studio\s+&nbsp;\s*([^\n&<]+)", soup.decode(), re.I)
        if m_studio:
            studio = re.sub(r"<[^>]+>", "", m_studio.group(1)).strip()

        # Label: criterion / arrow / etc — look for known label links
        label: Optional[str] = None
        for a in soup.find_all("a", href=re.compile(r"/movies/studio/")):
            ltxt = a.get_text(strip=True)
            if ltxt and len(ltxt) < 60:
                label = ltxt
                break

        # Runtime
        runtime_minutes: Optional[int] = None
        m_rt = re.search(r"(\d+)\s*min", full_text, re.I)
        if m_rt:
            rt = int(m_rt.group(1))
            if 30 < rt < 600:
                runtime_minutes = rt

        # IMDb link
        imdb_id: Optional[str] = None
        imdb_a = soup.find("a", href=re.compile(r"imdb\.com/title/(tt\d+)"))
        if imdb_a:
            m2 = re.search(r"(tt\d+)", imdb_a["href"])
            if m2:
                imdb_id = m2.group(1)

        # Movie rating (community star rating, 1-10)
        rating: Optional[float] = None
        m_rat = re.search(r"(\d+)\s*ratings?\.", full_text)
        m_score = re.search(r"(\d+\.\d+)\s*\n\s*\d+\s*ratings", full_text)
        if m_score:
            try:
                rating = float(m_score.group(1))
            except Exception:
                pass

        # Extras / special features
        extras = [li.get_text(strip=True)
                  for li in soup.select("div#extras li, ul.extras li, div#movie_review_extras li")
                  if li.get_text(strip=True)]

        # has_slipcover: derive from packaging string
        has_slipcover: Optional[bool] = None
        if packaging:
            has_slipcover = "slipcover" in packaging.lower()

        return BlurayComEdition(
            bluray_com_id=bid,
            title=title,
            year=year,
            url=url,
            cover_url=cover_url,
            disc_format=disc_format or "Blu-ray",
            region=region,
            disc_count=disc_count,
            disc_type=disc_type,
            bd_live=bd_live,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            original_aspect_ratio=original_aspect_ratio,
            video_codec=video_codec,
            video_bitrate_kbps=video_bitrate_kbps,
            hdr=hdr,
            audio_tracks=audio_tracks,
            subtitles=subtitles,
            packaging=packaging,
            has_slipcover=has_slipcover,
            studio=studio,
            label=label,
            release_date=release_date,
            runtime_minutes=runtime_minutes,
            genres=genres,
            popularity_pct=popularity_pct,
            collections_count=collections_count,
            fans_count=fans_count,
            user_rating_video=ur_video,
            user_rating_audio=ur_audio,
            user_rating_extras=ur_extras,
            user_rating_overall=ur_overall,
            imdb_id=imdb_id,
            rating=rating,
            extras=extras,
        )


# ---------------------------------------------------------------------------
# DVDCompare.net scraper
# ---------------------------------------------------------------------------

_DVDCOMPARE_BASE = "https://www.dvdcompare.net"


class DVDCompareClient:
    """HTML scraper for dvdcompare.net.  No API key required."""

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self, timeout: int = 15) -> None:
        self._session = requests.Session()
        self._session.headers.update(self._HEADERS)
        self._timeout = timeout

    def _get_html(self, url: str, params: Optional[Dict] = None) -> BeautifulSoup:
        resp = self._session.get(url, params=params, timeout=self._timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    def search(self, title: str) -> List[DVDCompareEdition]:
        """Search dvdcompare.net and return a list of matching film entries.

        DVDCompare uses a POST form with ``param`` (title) and
        ``searchtype=text``.  Results link to ``film.php?fid=<id>``.
        """
        resp = self._session.post(
            f"{_DVDCOMPARE_BASE}/comparisons/search.php",
            data={"param": title, "searchtype": "text"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results: List[DVDCompareEdition] = []
        for a in soup.find_all("a", href=re.compile(r"film\.php\?fid=\d+")):
            href = a.get("href", "")
            fid_match = re.search(r"fid=(\d+)", href)
            if not fid_match:
                continue
            fid = fid_match.group(1)
            raw_title = a.get_text(strip=True)
            # dvdcompare title lines look like "Alien (Blu-ray)\t\t\t\t(1979)"
            clean = re.sub(r"\s+", " ", raw_title).strip()
            results.append(DVDCompareEdition(
                dvdcompare_id=fid,
                title=clean,
                url=f"{_DVDCOMPARE_BASE}/comparisons/film.php?fid={fid}",
            ))
        return results

    def get_edition_by_fid(self, fid: str) -> Optional[DVDCompareEdition]:
        """Fetch full edition detail by dvdcompare.net film id."""
        url = f"{_DVDCOMPARE_BASE}/comparisons/film.php?fid={fid}"
        return self.get_edition(url)

    def get_edition(self, url: str) -> Optional[DVDCompareEdition]:
        """Fetch the full edition detail page from dvdcompare.net."""
        soup = self._get_html(url)
        return self._parse_edition_page(soup, url)

    def _parse_edition_page(self, soup: BeautifulSoup,
                             url: str) -> Optional[DVDCompareEdition]:
        """Parse a dvdcompare.net film comparison page.

        Returns one ``DVDCompareEdition`` (film-level) containing:
          - film metadata: title, director, tagline, imdb_id, CUTS summary
          - ``releases``: one ``DVDCompareRelease`` per regional edition
          - ``cut_runtimes``: parsed runtime entries from the CUTS: section
          - ``version`` / ``version_differences``: cut summary for resolvers
        """
        fid_match = re.search(r"fid=(\d+)", url)
        dvd_id = fid_match.group(1) if fid_match else url.rstrip("/").split("=")[-1]

        # Title from <title>: "Rewind @ www.dvdcompare.net - TITLE (YEAR)"
        page_title = soup.title.get_text() if soup.title else ""
        title_match = re.search(r"dvdcompare\.net\s*[-–]\s*(.+?)(?:\s*\(\d{4}\))?$",
                                 page_title)
        title = title_match.group(1).strip() if title_match else page_title.strip()
        if not title:
            return None

        content = soup.select_one("div#content") or soup

        # Director and tagline from the intro paragraph
        director: Optional[str] = None
        tagline: Optional[str] = None
        raw_html = content.decode_contents()
        m_dir = re.search(r"Director:\s*(.+?)(?:<br|<p|</p|\n)", raw_html, re.I)
        if m_dir:
            director = re.sub(r"<[^>]+>", "", m_dir.group(1)).strip()
        # Tagline is usually the first italic or quoted line before Director:
        m_tag = re.search(r"<[ib]>([^<]{10,200})</[ib]>", raw_html)
        if m_tag:
            tagline = re.sub(r"<[^>]+>", "", m_tag.group(1)).strip()

        # IMDb link
        imdb_id: Optional[str] = None
        imdb_a = soup.find("a", href=re.compile(r"imdb\.com/title/(tt\d+)"))
        if imdb_a:
            m = re.search(r"(tt\d+)", imdb_a["href"])
            if m:
                imdb_id = m.group(1)

        # ----------------------------------------------------------------
        # CUTS: section — film-level cut/runtime summary
        # Structure: <h3>CUTS:</h3> then <ul> of <li> per regional release
        # Each li: "Format Region Country- Distributor - cuts notes (HH:MM:SS)"
        # ----------------------------------------------------------------
        cuts_text: Optional[str] = None
        cut_runtimes: List[dict] = []
        cuts_tag = content.find(["h2", "h3"], string=re.compile(r"^CUTS:?$", re.I))
        if cuts_tag:
            ul = cuts_tag.find_next_sibling("ul")
            if ul:
                items = [li.get_text(" ", strip=True) for li in ul.find_all("li")]
                cuts_text = "\n".join(items)
                # Parse unique runtime timestamps: "Theatrical version (116:37)"
                # Use the first li only since all lis repeat the same runtimes
                seen_cuts: set = set()
                for m_rt in re.finditer(
                        r"((?:theatrical|director'?s.?cut|extended|assembly.?cut|"
                        r"special.?edition|unrated|international)[^(]*)\s*\((\d+):(\d+)\)",
                        cuts_text, re.I):
                    cut_name = m_rt.group(1).strip().rstrip("-– ").strip()
                    mins = int(m_rt.group(2))
                    secs = int(m_rt.group(3))
                    key = (cut_name.lower(), mins, secs)
                    if key not in seen_cuts:
                        seen_cuts.add(key)
                        cut_runtimes.append(CutRuntime(
                            cut=cut_name,
                            runtime_seconds=mins * 60 + secs,
                        ))

        # Determine version label
        version: Optional[str] = None
        version_differences: Optional[str] = cuts_text[:800] if cuts_text else None
        if cuts_text:
            has_dc = bool(re.search(r"director'?s.?cut", cuts_text, re.I))
            has_th = bool(re.search(r"theatrical", cuts_text, re.I))
            has_ex = bool(re.search(r"special.?edition|extended", cuts_text, re.I))
            has_ac = bool(re.search(r"assembly.?cut", cuts_text, re.I))
            if has_dc and has_th:
                version = "Multiple versions (Theatrical + Director's Cut)"
            elif has_dc:
                version = "Director's Cut"
            elif has_ac:
                version = "Assembly Cut"
            elif has_ex:
                version = "Extended / Special Edition"
            elif has_th:
                version = "Theatrical"

        # ----------------------------------------------------------------
        # Per-release parsing.
        # Each release is anchored by <a name=N> inside an <h3> element.
        # Content follows in a <ul class="specs"> or sibling <ul> until the
        # next anchored h3.  Each <li> has <div class="label"> and
        # <div class="description">.
        # ----------------------------------------------------------------
        releases: List[DVDCompareRelease] = []
        release_headers: List[str] = []  # legacy flat list

        for anchor in content.find_all("a", attrs={"name": re.compile(r"^\d+$")}):
            h3 = anchor.find_parent("h3") or anchor.find_parent(["h2", "h3"])
            if not h3:
                continue

            # Edition name is in the <i> tag inside the anchor (if present)
            i_tag = anchor.find("i")
            edition_name: Optional[str] = i_tag.get_text(strip=True) if i_tag else None
            # Main header text: the anchor text without the <i> part
            if i_tag:
                i_tag.decompose()  # temporarily remove to get clean header
            header_text = anchor.get_text(" ", strip=True)
            # Reconstruct full h3 text for legacy field
            full_header = (header_text + (" " + edition_name if edition_name else "")).strip()

            if re.search(r"OVERALL|CUTS|UPDATE", header_text, re.I):
                continue

            release_headers.append(full_header)

            release_id = anchor.get("name", "")
            disc_fmt: Optional[str] = None
            reg: Optional[str] = None
            country: Optional[str] = None
            distributor: Optional[str] = None

            # Header format: "Blu-ray ALL America - Twentieth Century Fox Home Entertainment"
            hdr_clean = re.sub(r"\s+", " ", header_text).strip()
            m_hdr = re.match(
                r"(Blu-ray|DVD|HD\s+DVD|UHD|4K)\s+([A-Z]+)\s+(.+?)(?:\s+-\s+(.+))?$",
                hdr_clean, re.I)
            if m_hdr:
                disc_fmt = m_hdr.group(1).strip()
                reg = m_hdr.group(2).strip()
                rest = m_hdr.group(3).strip()
                if " - " in rest:
                    parts = rest.split(" - ", 1)
                    country = parts[0].strip()
                    distributor = parts[1].strip()
                else:
                    country = rest
                if m_hdr.group(4) and not distributor:
                    distributor = m_hdr.group(4).strip()

            # Collect label/description pairs.
            # Structure: the h3 is inside a <li> inside the outer <ul>.
            # Sibling <li> elements of that wrapper contain the spec data.
            aspect_ratio: Optional[str] = None
            picture_format: Optional[str] = None
            case_type: Optional[str] = None
            soundtrack: List[str] = []
            rel_subtitles: List[str] = []
            rel_extras: List[str] = []
            rel_notes: Optional[str] = None

            # Navigate: h3 → parent li (wrapper) → sibling lis (specs)
            wrapper_li = h3.find_parent("li")
            spec_lis = []
            if wrapper_li:
                sib_li = wrapper_li.find_next_sibling("li")
                while sib_li:
                    # Stop if we've reached the next release's wrapper li
                    if sib_li.find("a", attrs={"name": re.compile(r"^\d+$")}):
                        break
                    spec_lis.append(sib_li)
                    sib_li = sib_li.find_next_sibling("li")

            for li in spec_lis:
                label_div = li.find("div", class_="label")
                desc_div = li.find("div", class_="description")
                if not label_div or not desc_div:
                    continue
                lbl = label_div.get_text(strip=True).rstrip(":").strip().lower()
                desc = desc_div.get_text(" ", strip=True)

                if lbl == "aspect ratio":
                    aspect_ratio = desc
                elif lbl == "picture format":
                    picture_format = re.sub(r"\s+", " ", desc).strip()
                elif lbl in ("case type", "case"):
                    case_type = desc.strip()
                elif lbl in ("soundtrack", "soundtracks", "soundtrack(s)", "audio"):
                    raw_st = desc_div.decode_contents()
                    soundtrack = [
                        re.sub(r"<[^>]+>", "", s).strip()
                        for s in re.split(r"<br\s*/?>", raw_st)
                        if re.sub(r"<[^>]+>", "", s).strip()
                    ]
                elif lbl == "subtitles":
                    rel_subtitles = [s.strip() for s in re.split(r",\s*", desc) if s.strip()]
                elif lbl == "extras":
                    raw_ex = desc_div.decode_contents()
                    rel_extras = [
                        re.sub(r"<[^>]+>", "", line).strip()
                        for line in re.split(r"<br\s*/?>", raw_ex)
                        if re.sub(r"<[^>]+>", "", line).strip()
                    ]
                elif lbl == "notes":
                    raw_notes = desc_div.decode_contents()
                    rel_notes = re.sub(r"<[^>]+>", " ", raw_notes)
                    rel_notes = re.sub(r"\s+", " ", rel_notes).strip()

            # (soundtrack fallback removed — already parsed in spec_lis loop above)

            releases.append(DVDCompareRelease(
                release_id=release_id,
                disc_format=disc_fmt,
                region=reg,
                country=country,
                distributor=distributor,
                edition_name=edition_name,
                aspect_ratio=aspect_ratio,
                picture_format=picture_format,
                case_type=case_type,
                soundtrack=soundtrack,
                subtitles=rel_subtitles,
                extras=rel_extras,
                notes=rel_notes,
            ))

        return DVDCompareEdition(
            dvdcompare_id=dvd_id,
            title=title,
            url=url,
            director=director,
            tagline=tagline,
            version=version,
            version_differences=version_differences,
            cut_runtimes=cut_runtimes,
            releases=releases,
            imdb_id=imdb_id,
        )


# ---------------------------------------------------------------------------
# Discogs API client
# ---------------------------------------------------------------------------

_DISCOGS_BASE = "https://api.discogs.com"
_DISCOGS_TOKEN_ENV = "DISCOGS_TOKEN"
# Formats that are video/film media — never music.  When searching these,
# genre defaults to "Non-Music" so music releases are excluded server-side.
_DISCOGS_VIDEO_FORMATS = frozenset({
    "Blu-ray", "UHD Blu-ray", "HD DVD", "DVD", "DVD-Video",
    "VHS", "Betamax", "Video 8",
    "Laserdisc",
    "Video",
})
_DISCOGS_GENRE_UNSET = object()  # sentinel — distinct from None (explicit opt-out)
# Discogs genre strings that indicate a music release.  A result that carries
# any of these alongside "Non-Music" is a concert film / music video, not a
# narrative film.  search_film() drops such results to avoid music false-positives.
_DISCOGS_MUSIC_GENRES = frozenset({
    "Electronic", "Rock", "Pop", "Jazz", "Classical", "Hip Hop", "Reggae",
    "Folk, World, & Country", "Funk / Soul", "Blues", "Latin",
    "Brass & Military", "Children's",
})


class DiscogsClient:
    """Client for the Discogs public REST API.

    Discogs is a **music database**.  It is authoritative for physical music
    releases (vinyl, CD, cassette), music video LaserDiscs / VHS / DVD
    (concert films, live performances), and soundtrack albums.

    Feature films (Alien, Blade Runner, etc.) have sparse-to-zero coverage
    on Discogs.  For narrative film disc lookups use DVDCompare or BlurayComClient.

    An optional personal access token (``DISCOGS_TOKEN`` env var or the
    *token* constructor arg) raises the rate limit from 25 to 60 req/min.
    Without a token the API still works for basic searches.
    """

    def __init__(self, token: Optional[str] = None, timeout: int = 15) -> None:
        self._token = token or os.environ.get(_DISCOGS_TOKEN_ENV)
        self._timeout = timeout
        # Discogs rate limits: 25 req/min unauthenticated, 60/min with token.
        # _min_interval is the floor sleep between consecutive requests.
        self._min_interval = 2.5 if not self._token else 1.0
        self._last_request: float = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "metadatarr/1.0 +https://github.com/JarbasAl/metadatarr",
            "Accept": "application/json",
        })
        if self._token:
            self._session.headers["Authorization"] = f"Discogs token={self._token}"

    def _get(self, path: str, params: Optional[Dict] = None) -> dict:
        import time as _time
        elapsed = _time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            _time.sleep(self._min_interval - elapsed)
        resp = self._session.get(f"{_DISCOGS_BASE}{path}",
                                 params=params, timeout=self._timeout)
        self._last_request = _time.monotonic()
        resp.raise_for_status()
        return resp.json()

    def search(self, title: str, *,
               fmt: str = "Blu-ray",
               media_type: str = "release",
               genre=_DISCOGS_GENRE_UNSET,
               per_page: int = 10) -> List[DiscogsSearchHit]:
        """Search the Discogs database for physical releases.

        Args:
            title:      Film / album title to search for.
            fmt:        Discogs format string — ``"Blu-ray"``, ``"DVD"``,
                        ``"VHS"``, ``"Laserdisc"``, ``"Vinyl"``, etc.
            media_type: Discogs type — ``"release"`` (default) or ``"master"``.
            genre:      Discogs genre filter.  When omitted, video formats
                        (Laserdisc, DVD, VHS, Blu-ray, …) automatically use
                        ``"Non-Music"`` to exclude music releases.  Pass
                        ``genre=None`` to disable filtering entirely, or
                        ``genre="Stage & Screen"`` for concert films.
            per_page:   Max results to return (Discogs caps at 100).
        """
        if genre is _DISCOGS_GENRE_UNSET:
            genre = "Non-Music" if fmt in _DISCOGS_VIDEO_FORMATS else None
        params: Dict = {
            "q": title,
            "type": media_type,
            "format": fmt,
            "per_page": per_page,
            "page": 1,
        }
        if genre:
            params["genre"] = genre
        data = self._get("/database/search", params=params)
        hits = []
        for item in data.get("results", []):
            try:
                hits.append(DiscogsSearchHit.model_validate(item))
            except Exception:
                continue
        return hits

    def search_video(self, title: str, *,
                     fmt: str = "Laserdisc",
                     per_page: int = 10) -> List[DiscogsSearchHit]:
        """Search for music video / concert film releases on physical video media.

        Discogs indexes concert film LaserDiscs, VHS releases of live performances,
        and official music video compilations.  It does NOT meaningfully index
        narrative feature films (Alien, Blade Runner, etc.) on any format.

        For video formats ``search()`` already defaults to ``genre="Non-Music"``
        server-side.  This method adds a client-side pass that drops any result
        carrying a music genre tag (Electronic, Rock, …) — those are music
        releases on video, not standalone documentary/concert films.

        Falls back to ``genre="Stage & Screen"`` so concert films tagged
        "Stage & Screen" (e.g. Pink Floyd Live at Pompeii) are still found.
        """
        def _is_video(hit: DiscogsSearchHit) -> bool:
            return not (_DISCOGS_MUSIC_GENRES & set(hit.genre))

        hits = self.search(title, fmt=fmt, per_page=per_page)
        video_hits = [h for h in hits if _is_video(h)]
        if video_hits:
            return video_hits
        stage_hits = self.search(title, fmt=fmt, genre="Stage & Screen", per_page=per_page)
        return [h for h in stage_hits if _is_video(h)]

    def search_film(self, title: str, *,
                    fmt: str = "Laserdisc",
                    per_page: int = 10) -> List[DiscogsSearchHit]:
        """Deprecated alias for :meth:`search_video`."""
        return self.search_video(title, fmt=fmt, per_page=per_page)

    def get_release(self, release_id: int) -> Optional[DiscogsRelease]:
        """Fetch full release detail by Discogs numeric id.

        The returned :class:`DiscogsRelease` includes all fields now exposed:
        identifiers (barcodes, matrix), format descriptions (NTSC/PAL/CLV),
        community (have/want/rating), styles, tracklist, videos, series,
        companies, master_id, and market data.
        """
        try:
            data = self._get(f"/releases/{release_id}")
            return DiscogsRelease.model_validate(data)
        except Exception:
            return None

    def get_master(self, master_id: int) -> Optional[dict]:
        """Fetch a Discogs master release (the canonical record for all pressings).

        Returns the raw dict — master releases share the same schema as
        regular releases but add a ``versions_url`` field linking to all
        individual pressings.
        """
        try:
            return self._get(f"/masters/{master_id}")
        except Exception:
            return None

    def get_master_versions(self, master_id: int, *,
                             per_page: int = 50) -> List[dict]:
        """List all individual pressings/versions of a master release.

        Useful for finding every country pressing of a LaserDisc or VHS title.
        Returns raw version dicts with ``id``, ``country``, ``format``,
        ``label``, ``catno``, ``released`` fields.
        """
        try:
            data = self._get(f"/masters/{master_id}/versions",
                             params={"per_page": per_page, "page": 1})
            return data.get("versions", [])
        except Exception:
            return []
