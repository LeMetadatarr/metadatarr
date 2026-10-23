# SPDX-License-Identifier: Apache-2.0
"""Translation between catalogue schemes (``{"tmdb": "603"}`` plus a kind) and
the resolver's :class:`~mediavocab.models.ExternalIds` fields.

A scheme names the catalogue and the kind picks the record inside it: a TMDB
id is a movie id for a movie and a TV id for a series, a MusicBrainz id is an
artist, release-group or recording id for an artist, album or track."""
from __future__ import annotations

from typing import Dict, Optional

from mediavocab.models import ExternalIds

SERIES_KINDS = {"series", "season", "episode"}

_FIELD = {"imdb": "imdb", "tvdb": "tvdb", "tvmaze": "tvmaze", "trakt": "trakt_id", "wikidata": "wikidata",
          "anilist": "anilist_id", "mal": "mal_id", "anidb": "anidb_id", "openlibrary": "olid",
          "goodreads": "goodreads", "audible": "audible_asin", "librivox": "librivox_id",
          "apple_podcasts": "apple_podcast_id", "youtube": "youtube_channel_id"}
_MUSICBRAINZ = {"artist": "musicbrainz_artist", "album": "musicbrainz_release_group",
                "track": "musicbrainz_recording"}

#: ExternalIds person fields -> scheme, for the people of a title resolve
PERSON_FIELD_SCHEME = {"tmdb_person": "tmdb", "imdb_person": "imdb", "musicbrainz_artist": "musicbrainz",
                       "anilist_staff_id": "anilist", "anilist_studio_id": "anilist", "mal_person_id": "mal",
                       "mal_studio_id": "mal", "wikidata": "wikidata", "youtube_channel_id": "youtube",
                       "discogs_artist": "discogs", "musicbrainz_label": "musicbrainz"}


def native_field(scheme: str, kind: Optional[str], value: str) -> Optional[str]:
    """The ExternalIds field that holds ``scheme`` for an item of ``kind``, or None."""
    if scheme == "tmdb":
        return "tmdb_tv" if kind in SERIES_KINDS else "tmdb_movie"
    if scheme == "musicbrainz":
        return _MUSICBRAINZ.get(kind or "album")
    if scheme == "isbn":
        return "isbn_13" if len(value.replace("-", "")) == 13 else "isbn_10"
    if scheme == "discogs":
        return "discogs_artist" if kind == "artist" else "discogs_release"
    return _FIELD.get(scheme)


def to_native(ids: Dict[str, str], kind: Optional[str]) -> ExternalIds:
    """ExternalIds from ``{scheme: value}``; a value that does not fit its field is left out."""
    fields: Dict[str, object] = {}
    for scheme, value in ids.items():
        name = native_field(scheme, kind, value)
        if not name or name in fields:
            continue
        annotation = str(ExternalIds.model_fields[name].annotation)
        if "int" in annotation and "str" not in annotation:
            if not value.isdigit():
                continue
            fields[name] = int(value)
        else:
            fields[name] = value.replace("-", "") if scheme == "isbn" else value
    try:
        return ExternalIds(**fields)
    except ValueError:
        return ExternalIds()


def from_native(native: ExternalIds, kind: Optional[str]) -> Dict[str, str]:
    """``{scheme: value}`` from ExternalIds, keeping the fields that name an item of ``kind``."""
    out: Dict[str, str] = {}
    for scheme in ("tmdb", "musicbrainz", "isbn", "discogs", *_FIELD):
        for candidate in {native_field(scheme, kind, "0" * 13), native_field(scheme, kind, "0" * 10)}:
            value = getattr(native, candidate, None) if candidate else None
            if value not in (None, "") and scheme not in out:
                out[scheme] = str(value)
    return out


def person_ids(native: ExternalIds) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name, scheme in PERSON_FIELD_SCHEME.items():
        value = getattr(native, name, None)
        if value not in (None, ""):
            out.setdefault(scheme, str(value))
    return out
