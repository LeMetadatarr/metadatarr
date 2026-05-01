from typing import List, Optional
from pydantic import BaseModel, Field, AliasChoices, AliasPath, ConfigDict, field_validator, model_validator
from enum import Enum


class BaseMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    title: str = Field(validation_alias=AliasChoices("title", "Title", "artistName", "ArtistName", "artistname", "name"))
    overview: Optional[str] = Field(None, validation_alias=AliasChoices(
        AliasPath("Artist", "Overview"), 
        AliasPath("Artist", "Description"),
        "overview", 
        "Overview", 
        "Description"
    ))

class SonarrSeries(BaseMetadata):
    tvdb_id: int = Field(validation_alias="tvdbId")
    year: Optional[int] = None

class RadarrMovie(BaseMetadata):
    tmdb_id: int = Field(validation_alias=AliasChoices("tmdbId", "TmdbId"))
    year: Optional[int] = Field(None, validation_alias=AliasChoices("year", "Year"))

class LidarrArtist(BaseMetadata):
    id: str = Field(validation_alias=AliasChoices(AliasPath("Artist", "Id"), "id", "artistId", "Id"))
    name: str = Field(validation_alias=AliasChoices(AliasPath("Artist", "ArtistName"), "artistName", "ArtistName", "artistname", "name"))
    # title is semantically wrong for an artist; shadow it with a property so
    # callers that use BaseMetadata.title still work but get the artist name.
    title: str = Field(default="", exclude=True, validate_default=False)
    overview: Optional[str] = Field(None, validation_alias=AliasChoices(
        AliasPath("Artist", "Overview"),
        AliasPath("Artist", "Description"),
        "overview",
        "Overview",
        "Description"
    ))

    @model_validator(mode="after")
    def _sync_title(self) -> "LidarrArtist":
        object.__setattr__(self, "title", self.name)
        return self


class BookInfoSearchHit(BaseModel):
    """A single hit from rreading-glasses /search."""
    book_id: int = Field(validation_alias=AliasChoices("bookId", "BookId"))
    work_id: int = Field(validation_alias=AliasChoices("workId", "WorkId"))
    author_id: Optional[int] = Field(
        None, validation_alias=AliasChoices(AliasPath("author", "id"), AliasPath("Author", "Id"))
    )


class BookInfoBook(BaseModel):
    """A single edition returned inside a work payload."""
    model_config = ConfigDict(populate_by_name=True)

    foreign_id: int = Field(validation_alias=AliasChoices("ForeignId", "foreignId"))
    asin: Optional[str] = Field(None, validation_alias=AliasChoices("Asin", "asin"))
    isbn13: Optional[str] = Field(None, validation_alias=AliasChoices("Isbn13", "isbn13"))
    title: Optional[str] = Field(None, validation_alias=AliasChoices("Title", "title"))
    description: Optional[str] = Field(None, validation_alias=AliasChoices("Description", "description"))
    publisher: Optional[str] = Field(None, validation_alias=AliasChoices("Publisher", "publisher"))
    release_date: Optional[str] = Field(None, validation_alias=AliasChoices("ReleaseDate", "releaseDate"))
    image_url: Optional[str] = Field(None, validation_alias=AliasChoices("ImageUrl", "imageUrl"))
    url: Optional[str] = Field(None, validation_alias=AliasChoices("Url", "url"))
    format: Optional[str] = Field(None, validation_alias=AliasChoices("Format", "format"))
    language: Optional[str] = Field(None, validation_alias=AliasChoices("Language", "language"))
    num_pages: Optional[int] = Field(None, validation_alias=AliasChoices("NumPages", "numPages"))


class BookInfoWork(BaseModel):
    """rreading-glasses work payload (Goodreads or Hardcover backend)."""
    model_config = ConfigDict(populate_by_name=True)

    foreign_id: int = Field(validation_alias=AliasChoices("ForeignId", "foreignId"))
    title: str = Field(validation_alias=AliasChoices("Title", "title"))
    full_title: Optional[str] = Field(None, validation_alias=AliasChoices("FullTitle", "fullTitle"))
    short_title: Optional[str] = Field(None, validation_alias=AliasChoices("ShortTitle", "shortTitle"))
    url: Optional[str] = Field(None, validation_alias=AliasChoices("Url", "url"))
    release_date: Optional[str] = Field(None, validation_alias=AliasChoices("ReleaseDate", "releaseDate"))
    release_date_raw: Optional[str] = Field(None, validation_alias=AliasChoices("ReleaseDateRaw", "releaseDateRaw"))
    genres: List[str] = Field(default_factory=list, validation_alias=AliasChoices("Genres", "genres"))
    books: List[BookInfoBook] = Field(default_factory=list, validation_alias=AliasChoices("Books", "books"))
    related_works: List[int] = Field(default_factory=list, validation_alias=AliasChoices("RelatedWorks", "relatedWorks"))


class BookInfoAuthor(BaseModel):
    """rreading-glasses author payload."""
    model_config = ConfigDict(populate_by_name=True)

    foreign_id: int = Field(validation_alias=AliasChoices("ForeignId", "foreignId"))
    name: str = Field(validation_alias=AliasChoices("Name", "name"))
    description: Optional[str] = Field(None, validation_alias=AliasChoices("Description", "description"))
    url: Optional[str] = Field(None, validation_alias=AliasChoices("Url", "url"))
    image_url: Optional[str] = Field(None, validation_alias=AliasChoices("ImageUrl", "imageUrl"))
    works: List[BookInfoWork] = Field(default_factory=list, validation_alias=AliasChoices("Works", "works"))
    series: List[dict] = Field(default_factory=list, validation_alias=AliasChoices("Series", "series"))


def _strip_ol_key(value):
    """OpenLibrary returns keys like '/works/OL45804W'; reduce to 'OL45804W'."""
    if isinstance(value, str) and value.startswith("/"):
        return value.rsplit("/", 1)[-1]
    return value


def _flatten_description(value):
    """OpenLibrary description can be a str or {'type': '/type/text', 'value': '...'}."""
    if isinstance(value, dict):
        return value.get("value")
    return value


class OpenLibrarySearchHit(BaseModel):
    """A single doc from OpenLibrary /search.json."""
    model_config = ConfigDict(populate_by_name=True)

    work_key: Optional[str] = Field(None, validation_alias="key")
    title: Optional[str] = None
    author_names: List[str] = Field(default_factory=list, validation_alias="author_name")
    author_keys: List[str] = Field(default_factory=list, validation_alias="author_key")
    first_publish_year: Optional[int] = None
    edition_count: Optional[int] = None
    cover_id: Optional[int] = Field(None, validation_alias="cover_i")
    cover_edition_key: Optional[str] = None
    isbn: List[str] = Field(default_factory=list)
    language: List[str] = Field(default_factory=list)

    @property
    def work_id(self) -> Optional[str]:
        return _strip_ol_key(self.work_key) if self.work_key else None


class OpenLibraryWork(BaseModel):
    """OpenLibrary /works/{id}.json payload."""
    model_config = ConfigDict(populate_by_name=True)

    key: str
    title: str
    description: Optional[str] = None
    subjects: List[str] = Field(default_factory=list)
    covers: List[int] = Field(default_factory=list)
    first_publish_date: Optional[str] = None
    author_keys: List[str] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "OpenLibraryWork":
        author_keys = []
        for a in data.get("authors", []) or []:
            inner = a.get("author") if isinstance(a, dict) else None
            k = (inner or {}).get("key") if isinstance(inner, dict) else None
            if k:
                author_keys.append(_strip_ol_key(k))
        return cls(
            key=_strip_ol_key(data.get("key", "")),
            title=data.get("title", ""),
            description=_flatten_description(data.get("description")),
            subjects=data.get("subjects", []) or [],
            covers=data.get("covers", []) or [],
            first_publish_date=data.get("first_publish_date"),
            author_keys=author_keys,
        )


class OpenLibraryEdition(BaseModel):
    """OpenLibrary /books/{id}.json (edition) payload."""
    model_config = ConfigDict(populate_by_name=True)

    key: str
    title: str
    subtitle: Optional[str] = None
    isbn_10: List[str] = Field(default_factory=list)
    isbn_13: List[str] = Field(default_factory=list)
    publishers: List[str] = Field(default_factory=list)
    publish_date: Optional[str] = None
    number_of_pages: Optional[int] = None
    languages: List[str] = Field(default_factory=list)
    covers: List[int] = Field(default_factory=list)
    work_keys: List[str] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "OpenLibraryEdition":
        works = []
        for w in data.get("works", []) or []:
            k = w.get("key") if isinstance(w, dict) else None
            if k:
                works.append(_strip_ol_key(k))
        langs = []
        for lang in data.get("languages", []) or []:
            k = lang.get("key") if isinstance(lang, dict) else lang
            if k:
                langs.append(_strip_ol_key(k))
        return cls(
            key=_strip_ol_key(data.get("key", "")),
            title=data.get("title", ""),
            subtitle=data.get("subtitle"),
            isbn_10=data.get("isbn_10", []) or [],
            isbn_13=data.get("isbn_13", []) or [],
            publishers=data.get("publishers", []) or [],
            publish_date=data.get("publish_date"),
            number_of_pages=data.get("number_of_pages"),
            languages=langs,
            covers=data.get("covers", []) or [],
            work_keys=works,
        )


class OpenLibraryAuthor(BaseModel):
    """OpenLibrary /authors/{id}.json payload."""
    model_config = ConfigDict(populate_by_name=True)

    key: str
    name: str
    personal_name: Optional[str] = None
    bio: Optional[str] = None
    birth_date: Optional[str] = None
    death_date: Optional[str] = None
    photos: List[int] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "OpenLibraryAuthor":
        return cls(
            key=_strip_ol_key(data.get("key", "")),
            name=data.get("name") or data.get("personal_name") or data.get("fuller_name") or "",
            personal_name=data.get("personal_name"),
            bio=_flatten_description(data.get("bio")),
            birth_date=data.get("birth_date"),
            death_date=data.get("death_date"),
            photos=[p for p in (data.get("photos") or []) if isinstance(p, int) and p > 0],
        )


class AnnasArchiveBook(BaseModel):
    title: str
    author: str
    formats: Optional[str] = None
    md5: str
    cover_url: Optional[str] = None
    language: Optional[str] = None
    size: Optional[str] = None



# ---------------------------------------------------------------------------
# TheAudioDB
# ---------------------------------------------------------------------------

class AudioDBArtist(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(alias="idArtist")
    name: str = Field(alias="strArtist")
    label: Optional[str] = Field(None, alias="strLabel")
    label_id: Optional[str] = Field(None, alias="idLabel")
    genre: Optional[str] = Field(None, alias="strGenre")
    style: Optional[str] = Field(None, alias="strStyle")
    mood: Optional[str] = Field(None, alias="strMood")
    biography: Optional[str] = Field(None, alias="strBiography")
    country: Optional[str] = Field(None, alias="strCountry")
    country_code: Optional[str] = Field(None, alias="strCountryCode")
    formed_year: Optional[int] = Field(None, alias="intFormedYear")
    gender: Optional[str] = Field(None, alias="strGender")
    members: Optional[int] = Field(None, alias="intMembers")
    thumb_url: Optional[str] = Field(None, alias="strArtistThumb")
    logo_url: Optional[str] = Field(None, alias="strArtistLogo")
    fanart_url: Optional[str] = Field(None, alias="strArtistFanart")
    musicbrainz_id: Optional[str] = Field(None, alias="strMusicBrainzID")

    @field_validator("formed_year", "members", mode="before")
    @classmethod
    def _coerce_int(cls, v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None


class AudioDBAlbum(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(alias="idAlbum")
    artist_id: Optional[str] = Field(None, alias="idArtist")
    label_id: Optional[str] = Field(None, alias="idLabel")
    name: str = Field(alias="strAlbum")
    artist: Optional[str] = Field(None, alias="strArtist")
    year: Optional[int] = Field(None, alias="intYearReleased")
    genre: Optional[str] = Field(None, alias="strGenre")
    style: Optional[str] = Field(None, alias="strStyle")
    label: Optional[str] = Field(None, alias="strLabel")
    release_format: Optional[str] = Field(None, alias="strReleaseFormat")
    description: Optional[str] = Field(None, alias="strDescription")
    thumb_url: Optional[str] = Field(None, alias="strAlbumThumb")
    back_url: Optional[str] = Field(None, alias="strAlbumBack")
    score: Optional[float] = Field(None, alias="intScore")
    musicbrainz_id: Optional[str] = Field(None, alias="strMusicBrainzID")
    musicbrainz_artist_id: Optional[str] = Field(None, alias="strMusicBrainzArtistID")
    wikidata_id: Optional[str] = Field(None, alias="strWikidataID")
    discogs_id: Optional[str] = Field(None, alias="strDiscogsID")
    allmusic_id: Optional[str] = Field(None, alias="strAllMusicID")

    @field_validator("year", mode="before")
    @classmethod
    def _coerce_int(cls, v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None


class AudioDBTrack(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(alias="idTrack")
    album_id: Optional[str] = Field(None, alias="idAlbum")
    artist_id: Optional[str] = Field(None, alias="idArtist")
    title: str = Field(alias="strTrack")
    artist: Optional[str] = Field(None, alias="strArtist")
    album: Optional[str] = Field(None, alias="strAlbum")
    track_number: Optional[int] = Field(None, alias="intTrackNumber")
    duration_ms: Optional[int] = Field(None, alias="intDuration")
    genre: Optional[str] = Field(None, alias="strGenre")
    mood: Optional[str] = Field(None, alias="strMood")
    style: Optional[str] = Field(None, alias="strStyle")
    theme: Optional[str] = Field(None, alias="strTheme")
    description: Optional[str] = Field(None, alias="strDescriptionEN")
    thumb_url: Optional[str] = Field(None, alias="strTrackThumb")
    music_vid_url: Optional[str] = Field(None, alias="strMusicVid")
    music_vid_director: Optional[str] = Field(None, alias="strMusicVidDirector")
    music_vid_company: Optional[str] = Field(None, alias="strMusicVidCompany")
    music_vid_views: Optional[int] = Field(None, alias="intMusicVidViews")
    score: Optional[float] = Field(None, alias="intScore")
    musicbrainz_id: Optional[str] = Field(None, alias="strMusicBrainzID")
    musicbrainz_album_id: Optional[str] = Field(None, alias="strMusicBrainzAlbumID")
    musicbrainz_artist_id: Optional[str] = Field(None, alias="strMusicBrainzArtistID")

    @property
    def duration_seconds(self) -> Optional[float]:
        return self.duration_ms / 1000.0 if self.duration_ms else None

    @field_validator("track_number", "duration_ms", "music_vid_views", mode="before")
    @classmethod
    def _coerce_int(cls, v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
# TVmaze
# ---------------------------------------------------------------------------

class TVmazeNetwork(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[int] = None
    name: Optional[str] = None
    country_code: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, v):
        if isinstance(v, dict):
            v = dict(v)
            country = v.pop("country", None) or {}
            if isinstance(country, dict):
                v.setdefault("country_code", country.get("code"))
        return v


class TVmazeExternals(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tvrage: Optional[int] = None
    thetvdb: Optional[int] = None
    imdb: Optional[str] = None


class TVmazeShow(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int
    name: str
    url: Optional[str] = None
    show_type: Optional[str] = Field(None, alias="type")
    language: Optional[str] = None
    genres: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    runtime: Optional[int] = None
    average_runtime: Optional[int] = Field(None, alias="averageRuntime")
    premiered: Optional[str] = None
    ended: Optional[str] = None
    official_site: Optional[str] = Field(None, alias="officialSite")
    rating: Optional[float] = None
    network: Optional[TVmazeNetwork] = None
    web_channel: Optional[TVmazeNetwork] = Field(None, alias="webChannel")
    externals: Optional[TVmazeExternals] = None
    image_medium: Optional[str] = None
    image_original: Optional[str] = None
    summary: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, v):
        if isinstance(v, dict):
            v = dict(v)
            img = v.pop("image", None) or {}
            v.setdefault("image_medium", img.get("medium"))
            v.setdefault("image_original", img.get("original"))
            rating = v.get("rating")
            if isinstance(rating, dict):
                v["rating"] = rating.get("average")
        return v


class TVmazePerson(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    url: Optional[str] = None
    birthday: Optional[str] = None
    deathday: Optional[str] = None
    gender: Optional[str] = None
    country_code: Optional[str] = None
    image_medium: Optional[str] = None
    image_original: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, v):
        if isinstance(v, dict):
            v = dict(v)
            img = v.pop("image", None) or {}
            country = v.pop("country", None) or {}
            v.setdefault("image_medium", img.get("medium"))
            v.setdefault("image_original", img.get("original"))
            v.setdefault("country_code", country.get("code"))
        return v


class TVmazeSeason(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int
    number: int
    name: Optional[str] = None
    episode_order: Optional[int] = Field(None, alias="episodeOrder")
    premiere_date: Optional[str] = Field(None, alias="premiereDate")
    end_date: Optional[str] = Field(None, alias="endDate")
    image_medium: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, v):
        if isinstance(v, dict):
            v = dict(v)
            img = v.pop("image", None) or {}
            v.setdefault("image_medium", img.get("medium"))
        return v


class TVmazeCastMember(BaseModel):
    model_config = ConfigDict(extra="ignore")

    person: Optional[TVmazePerson] = None
    character_name: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, v):
        if isinstance(v, dict):
            v = dict(v)
            char = v.pop("character", None) or {}
            v.setdefault("character_name", char.get("name"))
        return v


# ---------------------------------------------------------------------------
# Physical disc (Blu-ray / DVD / LaserDisc / VHS)
# ---------------------------------------------------------------------------

class BlurayComAudioTrack(BaseModel):
    """A single audio track as reported by blu-ray.com."""
    model_config = ConfigDict(extra="ignore")
    codec: Optional[str] = None          # "Dolby Atmos", "DTS-HD MA", "PCM"
    channels: Optional[str] = None       # "7.1", "5.1", "2.0"
    language: Optional[str] = None
    sample_rate_khz: Optional[float] = None   # 48.0, 96.0
    bit_depth: Optional[int] = None           # 16, 24
    bitrate_kbps: Optional[int] = None
    is_descriptive: bool = False              # Audio Descriptive track


class BlurayComSearchHit(BaseModel):
    """A single search result from blu-ray.com."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    bluray_com_id: int
    title: str
    year: Optional[int] = None
    url: Optional[str] = None
    cover_url: Optional[str] = None
    rating: Optional[float] = None


class BlurayComEdition(BaseModel):
    """Full disc edition detail from blu-ray.com."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    bluray_com_id: int
    title: str
    year: Optional[int] = None
    url: Optional[str] = None
    cover_url: Optional[str] = None

    # Disc format & region
    disc_format: Optional[str] = None    # "Blu-ray", "4K UHD Blu-ray", "DVD"
    region: Optional[str] = None         # "A", "B", "C", "Free"
    disc_count: Optional[int] = None
    disc_type: Optional[str] = None      # "BD-25", "BD-50", "BD-100"
    bd_live: Optional[bool] = None

    # Video specs
    resolution: Optional[str] = None            # "1080p", "2160p"
    aspect_ratio: Optional[str] = None          # "2.40:1" (encoded)
    original_aspect_ratio: Optional[str] = None # "2.39:1" (OAR)
    video_codec: Optional[str] = None           # "HEVC", "AVC", "VC-1"
    video_bitrate_kbps: Optional[int] = None
    hdr: Optional[str] = None                   # "HDR10", "Dolby Vision", "HDR10+"

    # Audio
    audio_tracks: List[BlurayComAudioTrack] = Field(default_factory=list)

    # Subtitles
    subtitles: List[str] = Field(default_factory=list)

    # Packaging
    packaging: Optional[str] = None      # "Keep Case", "Steelbook", "Digipak", "Slipcover"
    has_slipcover: Optional[bool] = None

    # Release info
    studio: Optional[str] = None
    label: Optional[str] = None          # "Criterion", "Arrow", "Shout Factory"
    release_date: Optional[str] = None
    runtime_minutes: Optional[int] = None
    genres: List[str] = Field(default_factory=list)

    # Community stats
    popularity_pct: Optional[int] = None
    collections_count: Optional[int] = None
    fans_count: Optional[int] = None
    user_rating_video: Optional[float] = None
    user_rating_audio: Optional[float] = None
    user_rating_extras: Optional[float] = None
    user_rating_overall: Optional[float] = None

    # Cross-refs scraped from the page
    imdb_id: Optional[str] = None
    rating: Optional[float] = None
    extras: List[str] = Field(default_factory=list)   # special feature titles


class CutRuntime(BaseModel):
    """A single cut/version runtime entry from a DVDCompare CUTS: section."""
    cut: str                    # e.g. "Theatrical", "Director's Cut"
    runtime_seconds: int        # total seconds

    @property
    def runtime_minutes(self) -> float:
        return self.runtime_seconds / 60


class Stream(BaseModel):
    """A playable media stream from a known platform.

    Constructed from ``ExternalIds.streams`` — aggregates playable URLs and IDs
    stored in ``ExternalIds.extra`` into a typed, uniform list.
    """
    platform: str       # "bandcamp", "soundcloud", "youtube", "youtube_music", "radio"
    url: str            # fully-formed playable URL
    media_type: str     # "track", "album", "video", "playlist", "stream"
    id: Optional[str] = None   # raw ID when the URL was constructed from one


class DVDCompareRelease(BaseModel):
    """One regional release entry from a dvdcompare.net film page.

    DVDCompare pages aggregate every regional edition of a single title.
    Each release has its own region, distributor, cut info, audio, subtitles,
    extras, and notes.  This model represents one such entry.
    """
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    # Identity
    release_id: Optional[str] = None    # anchor id on the page (numeric string)
    disc_format: Optional[str] = None   # "Blu-ray", "DVD", "HD DVD", "UHD"
    region: Optional[str] = None        # "A", "B", "C", "ALL", "R1", "R2" …
    country: Optional[str] = None
    distributor: Optional[str] = None   # "Criterion Collection", "Fox", "Studio Canal"
    edition_name: Optional[str] = None  # "Special Edition", "Alien Anthology", etc.

    # Technical
    aspect_ratio: Optional[str] = None
    picture_format: Optional[str] = None  # "1080p24 AVC MPEG-4", "2160p HEVC"
    case_type: Optional[str] = None       # "Keep Case", "Steelbook"

    # Content
    soundtrack: List[str] = Field(default_factory=list)   # "English DTS-HD MA 5.1"
    subtitles: List[str] = Field(default_factory=list)
    extras: List[str] = Field(default_factory=list)        # bonus features text
    notes: Optional[str] = None          # reissues, UV copies, linked variants


class DVDCompareEdition(BaseModel):
    """A dvdcompare.net film page — one title, all regional releases.

    ``releases`` contains structured per-release data (one entry per regional
    edition listed on the page).  ``version`` / ``version_differences`` are
    the film-level cut summary from the CUTS: section.
    """
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    dvdcompare_id: Optional[str] = None
    title: str
    url: Optional[str] = None

    # Film-level metadata
    director: Optional[str] = None
    tagline: Optional[str] = None
    disc_format: Optional[str] = None   # dominant format on this page
    region: Optional[str] = None
    country: Optional[str] = None
    label: Optional[str] = None
    release_date: Optional[str] = None
    runtime_minutes: Optional[int] = None
    aspect_ratio: Optional[str] = None

    # DVDCompare's killer feature: explicit version metadata
    version: Optional[str] = None              # "Director's Cut", "Theatrical", etc.
    version_differences: Optional[str] = None  # full CUTS: text blob
    cut_runtimes: List[CutRuntime] = Field(default_factory=list)

    # Per-release structured data
    releases: List[DVDCompareRelease] = Field(default_factory=list)

    imdb_id: Optional[str] = None


class DiscogsIdentifier(BaseModel):
    """A single identifier record from Discogs (barcode, matrix, ASIN, etc.)."""
    model_config = ConfigDict(extra="ignore")
    type: str                    # "Barcode", "Matrix / Runout", "ASIN", "Label Code"
    value: str
    description: Optional[str] = None   # "Text", "Scanned"


class DiscogsFormatDetail(BaseModel):
    """Parsed format entry from a Discogs release."""
    model_config = ConfigDict(extra="ignore")
    name: str                            # "Laserdisc", "VHS", "Blu-ray", "DVD"
    qty: Optional[int] = None
    descriptions: List[str] = Field(default_factory=list)
    # e.g. ["12\"", "Single Sided", "Stereo", "NTSC", "CLV", "Widescreen"]
    text: Optional[str] = None           # free-text note on the format line


class DiscogsCommunity(BaseModel):
    """Collector community stats for a Discogs release."""
    model_config = ConfigDict(extra="ignore")
    have: int = 0
    want: int = 0
    rating_count: int = 0
    rating_average: Optional[float] = None
    data_quality: Optional[str] = None  # "Correct", "Needs Vote", etc.


class DiscogsSearchHit(BaseModel):
    """A single hit from the Discogs database search API."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: int
    title: str
    url: Optional[str] = None
    cover_image: Optional[str] = None
    year: Optional[int] = None
    format: List[str] = Field(default_factory=list)
    label: List[str] = Field(default_factory=list)
    country: Optional[str] = None
    catno: Optional[str] = None          # catalogue number
    genre: List[str] = Field(default_factory=list)
    style: List[str] = Field(default_factory=list)
    master_id: Optional[int] = None

    @field_validator("year", mode="before")
    @classmethod
    def _coerce_year(cls, v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None


class DiscogsRelease(BaseModel):
    """Full release detail from the Discogs releases API."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: int
    title: str
    uri: Optional[str] = None

    year: Optional[int] = None
    released: Optional[str] = None           # "2019-03-15" ISO date
    released_formatted: Optional[str] = None # "Mar 15, 2019" human date
    country: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None             # "Accepted", "Draft"
    data_quality: Optional[str] = None       # "Correct", "Needs Vote"
    master_id: Optional[int] = None
    master_url: Optional[str] = None

    # Structured format entries
    format_details: List[DiscogsFormatDetail] = Field(default_factory=list)
    format_quantity: Optional[int] = None

    # Raw dicts (full payloads kept for advanced use)
    formats: List[dict] = Field(default_factory=list)
    labels: List[dict] = Field(default_factory=list)
    artists: List[dict] = Field(default_factory=list)
    extraartists: List[dict] = Field(default_factory=list)
    companies: List[dict] = Field(default_factory=list)
    series: List[dict] = Field(default_factory=list)

    genres: List[str] = Field(default_factory=list)
    styles: List[str] = Field(default_factory=list)
    images: List[dict] = Field(default_factory=list)
    identifiers: List[DiscogsIdentifier] = Field(default_factory=list)
    tracklist: List[dict] = Field(default_factory=list)
    videos: List[dict] = Field(default_factory=list)
    community: Optional[DiscogsCommunity] = None

    # Market
    num_for_sale: Optional[int] = None
    lowest_price: Optional[float] = None
    estimated_weight: Optional[int] = None  # grams

    @property
    def label_names(self) -> List[str]:
        return [lb.get("name", "") for lb in self.labels if lb.get("name")]

    @property
    def format_names(self) -> List[str]:
        return [f.get("name", "") for f in self.formats if f.get("name")]

    @property
    def artist_names(self) -> List[str]:
        return [a.get("name", "") for a in self.artists if a.get("name")]

    @property
    def company_names(self) -> List[str]:
        return [c.get("name", "") for c in self.companies if c.get("name")]

    @property
    def barcode(self) -> Optional[str]:
        """First scanned barcode value, or None."""
        for ident in self.identifiers:
            if ident.type == "Barcode" and ident.description == "Scanned":
                return ident.value
        for ident in self.identifiers:
            if ident.type == "Barcode":
                return ident.value
        return None

    @property
    def primary_image_url(self) -> Optional[str]:
        for img in self.images:
            if img.get("type") == "primary":
                return img.get("uri")
        return self.images[0].get("uri") if self.images else None

    @property
    def thumbnail_url(self) -> Optional[str]:
        for img in self.images:
            if img.get("type") == "primary":
                return img.get("uri150")
        return self.images[0].get("uri150") if self.images else None

    @field_validator("year", mode="before")
    @classmethod
    def _coerce_year(cls, v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @field_validator("community", mode="before")
    @classmethod
    def _coerce_community(cls, v):
        if not isinstance(v, dict):
            return v
        rating = v.get("rating", {}) or {}
        return DiscogsCommunity(
            have=v.get("have", 0),
            want=v.get("want", 0),
            rating_count=rating.get("count", 0),
            rating_average=rating.get("average") or None,
            data_quality=v.get("data_quality"),
        )

    @field_validator("format_details", mode="before")
    @classmethod
    def _coerce_format_details(cls, v):
        return v  # populated in model_validator below

    @field_validator("identifiers", mode="before")
    @classmethod
    def _coerce_identifiers(cls, v):
        if not isinstance(v, list):
            return []
        out = []
        for item in v:
            try:
                out.append(DiscogsIdentifier.model_validate(item))
            except Exception:
                pass
        return out

    def model_post_init(self, __context) -> None:
        if not self.format_details and self.formats:
            details = []
            for f in self.formats:
                try:
                    qty_raw = f.get("qty")
                    details.append(DiscogsFormatDetail(
                        name=f.get("name", ""),
                        qty=int(qty_raw) if qty_raw else None,
                        descriptions=f.get("descriptions") or [],
                        text=f.get("text") or None,
                    ))
                except Exception:
                    pass
            object.__setattr__(self, "format_details", details)
