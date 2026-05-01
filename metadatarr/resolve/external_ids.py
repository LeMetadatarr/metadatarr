"""Pydantic model for external authoritative IDs.

Known fields are first-class so the schema is explicit; unknown ones land in
:attr:`extra` (string -> string), so a new provider can ship without breaking
validation.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# ISBN helpers — public; book providers and callers can import these.
# ---------------------------------------------------------------------------

def _isbn_digits(value: str) -> str:
    """Strip hyphens, spaces; uppercase a trailing 'x' check digit."""
    return "".join(ch for ch in value.upper() if ch.isdigit() or ch == "X")


def isbn10_to_13(isbn10: str) -> Optional[str]:
    """Convert a 10-char ISBN to its 13-char form. Returns ``None`` on bad input."""
    digits = _isbn_digits(isbn10)
    if len(digits) != 10:
        return None
    body = "978" + digits[:9]
    try:
        total = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(body))
    except ValueError:
        return None
    check = (10 - total % 10) % 10
    return body + str(check)


def isbn13_to_10(isbn13: str) -> Optional[str]:
    """Convert a 978-prefixed 13-char ISBN to its 10-char form. ``None`` otherwise."""
    digits = _isbn_digits(isbn13)
    if len(digits) != 13 or not digits.startswith("978"):
        return None
    body = digits[3:12]
    total = sum((10 - i) * int(c) for i, c in enumerate(body))
    rem = (11 - total % 11) % 11
    check = "X" if rem == 10 else str(rem)
    return body + check


def normalize_isbn(value: str) -> Optional[str]:
    """Return a clean ISBN with no hyphens/spaces, or ``None`` if unrecognised."""
    if not value:
        return None
    digits = _isbn_digits(value)
    if len(digits) in (10, 13):
        return digits
    return None


# (extra_key, platform, media_type, url_template_or_None)
# url_template uses {id} as the placeholder; None means the value IS the URL.
_STREAM_MAP = (
    ("soundcloud_track_url",       "soundcloud",    "track",    None),
    ("bandcamp_track_url",         "bandcamp",      "track",    None),
    ("bandcamp_album_url",         "bandcamp",      "album",    None),
    ("music_video_url",            "youtube",       "video",    None),
    ("youtube_video_id",           "youtube",       "video",    "https://www.youtube.com/watch?v={id}"),
    ("youtube_music_video_id",     "youtube_music", "video",    "https://music.youtube.com/watch?v={id}"),
    ("youtube_music_playlist_id",  "youtube_music", "playlist", "https://music.youtube.com/playlist?list={id}"),
    ("stream_url",                 "radio",         "stream",   None),
)


class ExternalIds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # MusicBrainz
    musicbrainz_recording: Optional[str] = None
    musicbrainz_release: Optional[str] = None
    musicbrainz_release_group: Optional[str] = None
    musicbrainz_work: Optional[str] = None
    musicbrainz_artist: Optional[str] = None

    # Video
    imdb: Optional[str] = None             # tt-id
    tmdb_movie: Optional[int] = None
    tmdb_tv: Optional[int] = None
    tvdb: Optional[int] = None

    # Books
    isbn_10: Optional[str] = None
    isbn_13: Optional[str] = None
    olid: Optional[str] = None
    goodreads: Optional[str] = None

    # Linked-data hub
    wikidata: Optional[str] = None         # Q-id

    # People (TMDB/IMDb person ids when known via film/TV providers).
    tmdb_person: Optional[int] = None
    imdb_person: Optional[str] = None      # nm-id

    # Encyclopaedia Metallum (metal-archives.com) ids.
    metal_archives_band: Optional[int] = None
    metal_archives_release: Optional[int] = None
    metal_archives_song: Optional[str] = None  # MA song search returns the
    # alphanumeric lyrics-id form; full Song records carry an int ma_id, but
    # at the search layer we only see the alphanumeric anchor.
    metal_archives_label: Optional[int] = None
    metal_archives_artist: Optional[int] = None  # MA artist (lineup member) id

    # Release variants
    fanedit_id: Optional[int] = None             # IFDB WordPress post ID
    derived_from_imdb: Optional[str] = None      # parent IMDb tt-id when this record IS a variant

    # Physical disc databases
    discogs_release: Optional[int] = None    # Discogs numeric release id
    bluray_com_id: Optional[int] = None      # blu-ray.com movie id
    dvdcompare_id: Optional[str] = None      # dvdcompare.net film slug / id

    # Anything else a provider produced that we don't have a slot for.
    extra: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_and_pair_isbn(self) -> "ExternalIds":
        """Canonicalise ISBN forms and back-fill the sibling representation.

        ``ISBN-10`` and ``ISBN-13`` (for 978-prefixed editions) describe the
        same edition; without normalisation we'd treat ``"0-261-10328-8"``
        and ``"9780261103283"`` as different identifiers and fail to merge
        records that came from providers using different conventions.
        """
        if self.isbn_10:
            self.isbn_10 = normalize_isbn(self.isbn_10) or self.isbn_10
        if self.isbn_13:
            self.isbn_13 = normalize_isbn(self.isbn_13) or self.isbn_13
        if self.isbn_10 and not self.isbn_13:
            self.isbn_13 = isbn10_to_13(self.isbn_10) or None
        elif self.isbn_13 and not self.isbn_10:
            self.isbn_10 = isbn13_to_10(self.isbn_13) or None
        return self

    def merge(self, other: "ExternalIds") -> "ExternalIds":
        """Field-wise merge — first-writer-wins semantics.

        ``self`` is treated as the higher-precedence source: any value it
        already holds is preserved, and ``other`` only fills in fields that
        ``self`` left empty. The same rule applies to ``extra``, so an
        ``extra`` key set by the higher-precedence source is never silently
        overwritten by a later (weaker) provider. Pair this with
        :func:`consolidate`, which sorts matches by confidence descending,
        to get a stability-weighted merge.
        """
        out = self.model_copy(deep=True)
        for name in type(self).model_fields:
            if name == "extra":
                continue
            cur = getattr(out, name)
            new = getattr(other, name)
            if cur in (None, "") and new not in (None, ""):
                setattr(out, name, new)
        merged_extra = dict(other.extra)   # weak source as the base...
        merged_extra.update(out.extra)     # ...overridden by the strong source
        out.extra = merged_extra
        return out

    def is_empty(self) -> bool:
        return self == ExternalIds()

    @property
    def streams(self) -> List["Stream"]:
        """Return all playable stream URLs as typed :class:`Stream` objects.

        Aggregates known streaming keys from ``extra``, constructing full URLs
        from raw IDs where needed (e.g. ``youtube_video_id`` →
        ``https://www.youtube.com/watch?v=<id>``).  Artist/album *page* URLs
        are intentionally excluded — only directly playable content is listed.
        """
        from metadatarr.models import Stream  # local import avoids circular dependency
        results: List[Stream] = []
        for key, platform, media_type, tmpl in _STREAM_MAP:
            val = self.extra.get(key)
            if not val:
                continue
            url = tmpl.format(id=val) if tmpl else val
            results.append(Stream(
                platform=platform,
                url=url,
                media_type=media_type,
                id=val if tmpl else None,
            ))
        return results
