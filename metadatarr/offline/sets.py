# SPDX-License-Identifier: Apache-2.0
"""The datasets the offline layer reads and how their columns map.

Every set is a public parquet dataset of the ``LeData`` Hugging Face
organisation. The column names below are the datasets' own; a shard that lacks
a title or identifier column is refused when the set is built.

A set either *fronts* a live provider (it answers that provider's title search,
its id enrichment and its catalogue lookup before the provider is asked) or
stands alone (it adds candidates and cross references no live provider gives).

``ids`` maps a column to an ``ExternalIds`` field, or to a key of
``ExternalIds.extra`` for an id the model has no field for. A column holding a
list contributes every value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

ORG = "LeData"


@dataclass(frozen=True)
class SetSpec:
    """One dataset and its column mapping.

    ``title``: columns tried in order for the display title.
    ``names``: further columns (text or lists of text) searchable by name.
    ``fields``: item field -> column, ``a|b`` taking the first column set.
    ``poster``: ``(column, template)`` building ``poster_url`` from the column.
    ``keep``: columns stored as the item's ``extra``.
    ``rank``: column ordering equal names, larger first.
    ``artist``: column holding the creator (text or list; the first is used).
    ``kind_by``: ``(column, {value: kind})`` overriding ``kind`` per row.
    ``lookups``: ``(scheme, kind)`` catalogue lookups this set answers;
    ``children`` is true when the live answer to them lists children, which a
    row cannot, so such a lookup is answered offline only without children.
    """

    name: str
    kind: str
    media: Tuple[str, ...]
    title: Tuple[str, ...]
    ids: Mapping[str, str] = field(default_factory=dict)
    names: Tuple[str, ...] = ()
    year: str = ""
    rank: str = ""
    artist: str = ""
    fields: Mapping[str, str] = field(default_factory=dict)
    runtime_unit: float = 1.0
    poster: Optional[Tuple[str, str]] = None
    keep: Tuple[str, ...] = ()
    front: str = ""
    lookups: Tuple[Tuple[str, str], ...] = ()
    children: bool = False
    kind_by: Optional[Tuple[str, Mapping[str, str]]] = None
    repo_name: str = ""

    @property
    def repo(self) -> str:
        return f"{ORG}/{self.repo_name or 'media-metadata-' + self.name}"

    @property
    def columns(self) -> Tuple[str, ...]:
        """Every column read, in a stable order, without duplicates."""
        cols = list(self.title) + list(self.ids) + list(self.names) + list(self.keep)
        for column in (self.year, self.rank, self.artist):
            cols.append(column)
        for spec in self.fields.values():
            cols.extend(spec.split("|"))
        if self.poster:
            cols.append(self.poster[0])
        if self.kind_by:
            cols.append(self.kind_by[0])
        return tuple(dict.fromkeys(c for c in cols if c))

    @property
    def required(self) -> Tuple[str, ...]:
        """Columns a shard must have: the title and every id column."""
        return tuple(dict.fromkeys((self.title[0], *self.ids)))


_ARTIST_KEEP = ("type", "gender", "country", "area", "end_date", "ended", "disambiguation", "tags")

SETS: Tuple[SetSpec, ...] = (
    SetSpec(
        name="musicbrainz-artists", kind="artist", media=("music",),
        title=("name",), names=("aliases",), year="begin_date",
        ids={"mb_id": "musicbrainz_artist"},
        fields={"sort_title": "sort_name", "release_date": "begin_date"},
        keep=(*_ARTIST_KEEP, "isni_codes", "ipi_codes"),
        lookups=(("musicbrainz", "artist"),), children=True,
    ),
    SetSpec(
        name="unified-artists", kind="artist", media=("music",),
        title=("name",), names=("aliases",), year="begin_date",
        ids={"mb_id": "musicbrainz_artist", "adb_id": "audiodb_artist_id", "ma_id": "metal_archives_band",
             "progarchives_id": "progarchives_id", "jazz_id": "jazz_id", "classical_id": "classical_id",
             "bandcamp_id": "bandcamp_band_id", "soundcloud_id": "soundcloud_user_id"},
        fields={"sort_title": "sort_name", "release_date": "begin_date", "overview": "biography_en"},
        keep=(*_ARTIST_KEEP, "sources", "style", "mood", "classical_period", "members", "website",
              "prog_genre", "jazz_genre", "themes", "label", "genres", "status", "soundcloud_username",
              "bandcamp_url"),
    ),
    SetSpec(
        name="artists", kind="artist", media=("music",),
        title=("name",), names=("aliases",), year="begin_date",
        ids={"mb_id": "musicbrainz_artist", "adb_id": "audiodb_artist_id", "ma_id": "metal_archives_band",
             "progarchives_id": "progarchives_id", "jazz_id": "jazz_id", "classical_id": "classical_id"},
        fields={"sort_title": "sort_name", "release_date": "begin_date", "overview": "biography_en"},
        keep=(*_ARTIST_KEEP, "sources", "style", "mood", "classical_period", "members", "website"),
    ),
    SetSpec(
        name="wikidata-entities", kind="entity", media=("generic",),
        title=("label_en",), year="inception_year",
        ids={"wikidata_id": "wikidata"},
        fields={"overview": "description_en"},
        keep=("entity_type", "domain", "country", "country_qid", "website", "dissolved_year", "location"),
    ),
    SetSpec(
        name="openlibrary-books", kind="book", media=("book",),
        title=("title",), year="first_publish_year", rank="edition_count", artist="authors",
        ids={"olid": "olid", "isbn_10": "isbn_10", "isbn_13": "isbn_13"},
        fields={"original_title": "subtitle"},
        poster=("cover_i", "https://covers.openlibrary.org/b/id/{}-M.jpg"),
        keep=("authors", "author_key", "publisher", "edition_count", "subjects", "language",
              "number_of_pages_median", "ebook_access"),
        front="openlibrary", lookups=(("openlibrary", "book"), ("isbn", "book")),
    ),
    SetSpec(
        name="gutenberg-books", kind="book", media=("book",),
        title=("title",), rank="download_count", artist="authors",
        ids={"gutenberg_id": "gutenberg_id"},
        keep=("authors", "translators", "subjects", "bookshelves", "languages", "copyright", "download_count",
              "has_text", "has_epub"),
    ),
    SetSpec(
        name="librivox-audiobooks", kind="audiobook", media=("audiobook",),
        title=("title",), year="copyright_year", artist="authors",
        ids={"librivox_id": "librivox_id"},
        fields={"overview": "description", "runtime_min": "totaltimesecs"}, runtime_unit=1 / 60,
        keep=("language", "copyright_year", "num_sections", "url_librivox", "url_rss", "url_zip_file",
              "url_text_source", "authors"),
        front="librivox", lookups=(("librivox", "audiobook"),), children=True,
    ),
    SetSpec(
        name="tvmaze-shows", kind="series", media=("episodic_series",),
        title=("name",),
        ids={"tvmaze_id": "tvmaze", "imdb_id": "imdb", "thetvdb_id": "tvdb", "tvrage_id": "tvrage_id"},
        fields={"release_date": "premiered", "runtime_min": "average_runtime|runtime", "overview": "summary",
                "poster_url": "image_medium"},
        keep=("type", "language", "genres", "status", "ended", "network_name", "network_country",
              "rating_average", "official_site", "schedule_days", "schedule_time"),
        front="tvmaze", lookups=(("tvmaze", "series"), ("tvdb", "series"), ("imdb", "series")), children=True,
    ),
    SetSpec(
        name="anilist-anime", kind="series", media=("episodic_series", "movie"),
        title=("title_english", "title_romaji", "title_native"), names=("title_romaji", "title_native",
                                                                       "title_english"),
        year="season_year", rank="popularity",
        ids={"anilist_id": "anilist_id", "mal_id": "mal_id"},
        fields={"original_title": "title_native", "release_date": "start_date", "runtime_min": "duration"},
        keep=("format", "status", "episodes", "genres", "studios", "average_score", "country_of_origin",
              "source_material", "season", "tags", "is_adult", "end_date"),
        kind_by=("format", {"MOVIE": "movie"}),
        front="anilist", lookups=(("anilist", "series"), ("anilist", "movie"), ("mal", "series"),
                                  ("mal", "movie")),
    ),
    SetSpec(
        name="jikan-manga", kind="book", media=("comic",),
        title=("title", "title_english", "title_japanese"),
        names=("title_english", "title_japanese", "aliases"), rank="members", artist="authors",
        ids={"mal_id": "mal_id"},
        fields={"original_title": "title_japanese", "release_date": "published_from", "overview": "synopsis"},
        keep=("type", "status", "chapters", "volumes", "authors", "serializations", "genres", "themes",
              "demographics", "score", "scored_by", "popularity", "published_to"),
        front="jikan_manga",
    ),
    SetSpec(
        name="podcastindex-podcasts", kind="show", media=("podcast",),
        title=("title",), rank="episode_count", artist="author",
        ids={"itunes_id": "apple_podcast_id", "feed_url": "feed_url"},
        fields={"overview": "description", "poster_url": "image"},
        keep=("author", "genres", "language", "episode_count", "explicit", "url", "country_charts"),
    ),
    SetSpec(
        name="listennotes-podcasts", kind="show", media=("podcast",),
        title=("title",), rank="listen_score",
        ids={"ln_id": "listen_notes_id"},
        fields={"overview": "description", "poster_url": "image"},
        keep=("ln_url", "episode_count", "listen_score", "global_rank"),
    ),
    SetSpec(
        name="steam-games", kind="game", media=("game",),
        title=("name",), year="release_date", rank="positive_reviews", artist="developer",
        ids={"steam_appid": "steam_appid"},
        fields={"overview": "short_description", "release_date": "release_date"},
        keep=("developer", "publisher", "genres", "categories", "price_usd", "is_free", "metacritic_score",
              "positive_reviews", "negative_reviews", "owners", "type"),
    ),
    SetSpec(
        name="radiobrowser-stations", kind="station", media=("radio",),
        title=("name",), rank="votes",
        ids={"stationuuid": "stationuuid"},
        fields={"poster_url": "favicon"},
        keep=("url", "url_resolved", "homepage", "country", "countrycode", "state", "language", "tags",
              "codec", "bitrate", "clickcount"),
    ),
    SetSpec(
        name="metal-archives", kind="artist", media=("music",),
        title=("name",),
        ids={"band_id": "metal_archives_band"},
        keep=("country", "location", "status", "formed_in", "genres", "themes", "years_active",
              "current_label_name", "url"),
    ),
    SetSpec(
        name="progarchives-artists", kind="artist", media=("music",),
        title=("name",),
        ids={"artist_id": "progarchives_id"},
        fields={"overview": "bio"},
        keep=("genre", "country", "url", "n_albums"),
    ),
    SetSpec(
        name="jazz-artists", kind="artist", media=("music",),
        title=("name",),
        ids={"artist_slug": "jazz_id"},
        fields={"overview": "bio"},
        keep=("genres", "genre", "url", "n_albums"),
    ),
    SetSpec(
        name="deezer-playlists", kind="playlist", media=("playlist",),
        title=("title",), rank="fans", artist="creator_name",
        ids={"deezer_id": "deezer_playlist_id"},
        fields={"overview": "description", "release_date": "creation_date"},
        keep=("creator_name", "nb_tracks", "fans", "genres", "url", "source_genre", "duration_seconds",
              "tracks"),
    ),
    SetSpec(
        name="ytmusic-playlists", kind="playlist", media=("playlist",),
        title=("title",), artist="author",
        ids={"ytm_id": "ytmusic_playlist_id"},
        fields={"overview": "description"},
        keep=("author", "track_count", "duration_seconds", "source_category", "tracks"),
    ),
    SetSpec(
        name="fanedits", kind="movie", media=("movie",),
        title=("title",), artist="faneditor",
        ids={"fanedit_id": "fanedit_id", "imdb_id": "derived_from_imdb"},
        fields={"original_title": "original_title", "overview": "synopsis",
                "release_date": "fanedit_release_date", "poster_url": "cover_url"},
        keep=("faneditor", "genre", "franchise", "fanedit_type", "url", "slug", "editor_rating",
              "user_rating", "original_release_date", "fanedit_running_time"),
        front="pyfanedit",
    ),
)

BY_NAME: Dict[str, SetSpec] = {s.name: s for s in SETS}
