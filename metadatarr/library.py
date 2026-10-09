# SPDX-License-Identifier: Apache-2.0
"""Local media-library tagger — scan, resolve, write NFO sidecars.

NON-DESTRUCTIVE BY DEFAULT: this module only ever *reads* files under a
library root and *writes* ``<basename>.nfo`` sidecars next to them by
default. It never edits, remuxes, or deletes the underlying media file's
*content*.

Renaming/organizing the media file itself (``<title> (<year>)
{tmdb-<id>}.ext``) is available as an OPT-IN, off-by-default ``rename``
capability (see :func:`tag_file`/:func:`tag_library`'s ``rename`` param and
the CLI's ``--rename`` flag) — it is destructive (moves user files) and is
guarded by several safety rules: only confidently-matched files are ever
renamed, ``dry_run`` still previews without moving anything, a rename never
overwrites an existing file at the target path, and the underlying move is
atomic within a filesystem.

Embedding resolved metadata into a MUSIC file's own tags (so it travels
with the file to any player, not just the ``.nfo``) is likewise an OPT-IN,
off-by-default ``write_tags`` capability (see :func:`tag_file`/
:func:`tag_library`'s ``write_tags`` param and the CLI's ``--write-tags``
flag) — it is destructive (rewrites the file's tag block) and is guarded
by the same class of safety rules: only confidently-matched music files
are ever written, ``dry_run`` still previews without touching the file,
unrelated existing tags are never clobbered, and an optional
``backup_tags`` sidecar preserves the pre-write tags.

This is a metadatarr-native feature (not media-archivist's): tagging an
existing local library is a metadata operation — scan the tree, build a
``Signals`` bag per file, resolve it via :mod:`metadatarr.resolve`, and
write a Kodi/Jellyfin ``.nfo`` via :mod:`metadatarr.nfo`.

Pipeline: :func:`scan` walks the tree -> :func:`extract_signals` builds a
``mediavocab`` ``Signals`` bag per file (embedded tags / filename parsing,
optionally sharpened by ``guessit``/``mutagen`` when installed) ->
:func:`tag_file` resolves it against metadatarr's resolver and writes the
``.nfo``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals

from metadatarr.nfo import nfo_xml
from metadatarr.resolve import enrich, resolve

LOG = logging.getLogger("metadatarr.library")

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".webm", ".mov", ".m4v", ".ts"}
AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aac"}

# Kodi/Jellyfin local-extras filename suffixes: "<basename>-<suffix>.ext".
# https://jellyfin.org/docs/general/server/media/movies/#extras
_EXTRAS_SUFFIXES = (
    "trailer", "sample", "behindthescenes", "featurette",
    "deleted", "interview", "scene", "short", "clip", "other",
)
_EXTRAS_SUFFIX_RE = re.compile(
    r"[-.](" + "|".join(_EXTRAS_SUFFIXES) + r")$", re.IGNORECASE
)
# A standalone ".sample." / "-sample-" / trailing ".sample" token anywhere
# in the path (deliberately narrow so "The Sample" as a title is untouched).
_LOOSE_SAMPLE_RE = re.compile(r"[.\-_]sample(?:[.\-_]|$)", re.IGNORECASE)

_EXTRAS_DIR_NAMES = {
    "trailers", "extras", "featurettes", "behind the scenes",
    "deleted scenes", "interviews", "sample", "samples", "other",
}

try:
    import guessit as _guessit  # type: ignore
except ImportError:  # pragma: no cover — exercised via monkeypatch in tests
    _guessit = None

try:
    import mutagen as _mutagen  # type: ignore
except ImportError:  # pragma: no cover — exercised via monkeypatch in tests
    _mutagen = None


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

@dataclass
class LocalMediaFile:
    """A media file discovered under a scanned root."""

    path: Path
    kind: Literal["video", "music"]


def _is_extra_path(path: Path) -> bool:
    """True if *path* is a Jellyfin/Kodi local-extra (trailer/sample/etc)."""
    for part in path.parent.parts:
        if part.lower() in _EXTRAS_DIR_NAMES:
            return True
    stem = path.stem
    if _EXTRAS_SUFFIX_RE.search(stem):
        return True
    if _LOOSE_SAMPLE_RE.search(path.name):
        return True
    return False


def scan(root: str, *, media: str = "both", skip_extras: bool = True,
        stats: Optional[Dict[str, int]] = None) -> Iterator[LocalMediaFile]:
    """Recursively walk *root*, yielding every matched media file.

    ``media`` restricts the walk to ``"video"``, ``"music"``, or the
    default ``"both"``. Non-media files (subtitles, artwork, existing
    ``.nfo`` sidecars, etc.) are silently skipped.

    When ``skip_extras`` (the default) is true, Jellyfin/Kodi local-extras
    — trailers, samples, behind-the-scenes, deleted scenes, etc, whether
    named via suffix (``Foo-trailer.mkv``) or filed under a conventional
    folder (``Trailers/``, ``Extras/``) — are excluded from the walk. Pass
    a ``stats`` dict to have the count of skipped extras recorded under
    the ``"skipped_extras"`` key.
    """
    want_video = media in ("both", "video")
    want_music = media in ("both", "music")
    root_path = Path(root)
    for dirpath, _dirnames, filenames in os.walk(root_path):
        for name in filenames:
            path = Path(dirpath) / name
            ext = path.suffix.lower()
            is_media = (want_video and ext in VIDEO_EXTS) or (want_music and ext in AUDIO_EXTS)
            if not is_media:
                continue
            if skip_extras and _is_extra_path(path):
                if stats is not None:
                    stats["skipped_extras"] = stats.get("skipped_extras", 0) + 1
                LOG.debug("skipping extra: %s", path)
                continue
            kind = "video" if ext in VIDEO_EXTS else "music"
            yield LocalMediaFile(path=path, kind=kind)


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"(?:\(|\.|\s)((?:19|20)\d{2})(?:\)|\.|\s|$)")
_SXXEXX_RE = re.compile(r"[Ss](\d{1,2})[EeXx](\d{1,3})")
_RELEASE_JUNK_RE = re.compile(
    r"\b(1080p|720p|2160p|4k|hdr|x264|x265|h264|h265|hevc|webrip|web-dl|webdl|"
    r"bluray|brrip|dvdrip|hdtv|amzn|nf|remux|proper|repack|extended|"
    r"[a-z0-9]+-group)\b",
    re.IGNORECASE,
)


def _clean_title(text: str) -> str:
    text = text.replace(".", " ").replace("_", " ")
    text = _RELEASE_JUNK_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" -.")
    return text


def _parse_video_filename(stem: str) -> Signals:
    """Regex fallback filename parser for video files.

    Handles "Title (2010)", "Show.Name.S01E02", "Title.2010.1080p".
    """
    m = _SXXEXX_RE.search(stem)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        title = _clean_title(stem[: m.start()])
        return Signals(
            title=title or None,
            season=season,
            episode=episode,
            medium=MediaType.EPISODIC_SERIES,
        )

    year = None
    ym = _YEAR_RE.search(stem)
    title_part = stem
    if ym:
        year = int(ym.group(1))
        title_part = stem[: ym.start()]
    title = _clean_title(title_part)
    return Signals(
        title=title or None,
        year=year,
        medium=MediaType.MOVIE,
    )


def _guessit_video_signals(path: Path) -> Optional[Signals]:
    if _guessit is None:
        return None
    try:
        guess = _guessit.guessit(path.name)
    except Exception:
        LOG.exception("guessit failed on %s; falling back to filename parsing", path)
        return None
    gtype = str(guess.get("type") or "").lower()
    title = guess.get("title")
    if not title:
        return None
    if gtype == "episode":
        season = guess.get("season")
        episode = guess.get("episode")
        return Signals(
            title=str(title),
            season=int(season) if isinstance(season, int) else None,
            episode=int(episode) if isinstance(episode, int) else None,
            medium=MediaType.EPISODIC_SERIES,
        )
    year = guess.get("year")
    return Signals(
        title=str(title),
        year=int(year) if isinstance(year, int) else None,
        medium=MediaType.MOVIE,
    )


_ARTIST_TITLE_RE = re.compile(r"^\s*(.+?)\s*-\s*(.+?)\s*$")
_TRACK_NUM_RE = re.compile(r"^\s*\d{1,3}[\s._-]+(.+?)\s*$")


def _parse_music_filename(stem: str) -> Signals:
    """Regex fallback for music files: 'Artist - Title' or 'NN Title'."""
    m = _ARTIST_TITLE_RE.match(stem)
    if m:
        return Signals(artist=m.group(1) or None, title=m.group(2) or None,
                        medium=MediaType.MUSIC)
    m = _TRACK_NUM_RE.match(stem)
    if m:
        return Signals(title=m.group(1) or None, medium=MediaType.MUSIC)
    return Signals(title=stem or None, medium=MediaType.MUSIC)


def _mutagen_music_signals(path: Path) -> Optional[Signals]:
    if _mutagen is None:
        return None
    try:
        audio = _mutagen.File(path, easy=True)  # type: ignore[attr-defined]
    except Exception:
        LOG.exception("mutagen failed on %s; falling back to filename parsing", path)
        return None
    if not audio or not audio.tags:
        return None

    def _first(key: str) -> Optional[str]:
        vals = audio.tags.get(key)
        return vals[0] if vals else None

    title = _first("title")
    artist = _first("artist")
    album = _first("album")
    date = _first("date")
    if not (title or artist or album):
        return None
    year = None
    if date:
        m = re.match(r"(\d{4})", str(date))
        if m:
            year = int(m.group(1))
    return Signals(
        title=title, artist=artist, medium=MediaType.MUSIC, year=year,
    ) if title or artist else None


_FFPROBE_TIMEOUT_S = 10


def _ffprobe_tags(path: Path) -> Dict[str, Any]:
    """Read embedded container-format tags via ``ffprobe``, best-effort.

    Optional: only runs when ``ffprobe`` (shipped with ffmpeg, not a pip
    dependency) is on ``PATH``. Real-library files often carry a correct
    embedded ``title``/``date`` — and sometimes a Radarr/Jellyfin-stamped
    tmdb/imdb tag — in the container even when the filename is messy, so
    this is read *in addition to* filename parsing, never instead of it.

    Metadata-only (``-show_format``, no decode), bounded by a short
    timeout. Any failure (binary missing, timeout, malformed output, not a
    real media file) is swallowed and returns ``{}`` so the caller silently
    falls back to filename/guessit signals — this must never abort a scan.
    Uses an explicit argument list, never ``shell=True``.
    """
    if shutil.which("ffprobe") is None:
        return {}
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=_FFPROBE_TIMEOUT_S, check=False,
        )
        data = json.loads(proc.stdout or "{}")
    except Exception:
        LOG.debug("ffprobe failed on %s", path, exc_info=True)
        return {}
    tags = data.get("format", {}).get("tags", {})
    return tags if isinstance(tags, dict) else {}


def _apply_ffprobe_overrides(signals: Signals, path: Path) -> Signals:
    """Sharpen *signals* with embedded container tags, when available.

    A non-trivial embedded ``title`` tag always wins over a guessit/regex
    title (the latter can truncate, see :func:`_full_title_candidate`'s
    docstring), and an embedded ``date``/``year`` tag fills in a year the
    filename lacked. No-op when ffprobe found nothing.
    """
    tags = _ffprobe_tags(path)
    if not tags:
        return signals
    lower = {str(k).lower(): v for k, v in tags.items()}
    updates: Dict[str, Any] = {}

    title = lower.get("title")
    if title and str(title).strip():
        updates["title"] = str(title).strip()

    if signals.year is None:
        date = lower.get("date") or lower.get("year")
        if date:
            m = re.match(r"(\d{4})", str(date))
            if m:
                updates["year"] = int(m.group(1))

    if not updates:
        return signals
    return signals.model_copy(update=updates)


# ffprobe/container-tag keys that carry a Radarr/Jellyfin-style embedded id,
# mirroring the filename convention handled by :func:`extract_embedded_ids`.
_FFPROBE_TMDB_KEYS = ("tmdb", "tmdbid")
_FFPROBE_IMDB_KEYS = ("imdb", "imdbid", "imdb_id")


def _embedded_ids_from_tags(tags: Dict[str, Any], *,
                            is_true_episodic: bool = False) -> Optional[ExternalIds]:
    """Extract tmdb/imdb ids from ffprobe container tags, if present.

    Same acceptance rules as :func:`extract_embedded_ids`: a bare tmdb tag
    defaults to ``tmdb_movie`` unless *is_true_episodic* (derived from an
    actual SxxEyy filename marker, never a type guess).
    """
    if not tags:
        return None
    lower = {str(k).lower(): v for k, v in tags.items()}
    ids: Dict[str, Any] = {}

    for key in _FFPROBE_TMDB_KEYS:
        val = lower.get(key)
        if val is not None and str(val).strip().isdigit():
            ids["tmdb_tv" if is_true_episodic else "tmdb_movie"] = int(str(val).strip())
            break

    for key in _FFPROBE_IMDB_KEYS:
        val = lower.get(key)
        if val is not None and re.match(r"^tt\d+$", str(val).strip(), re.IGNORECASE):
            ids["imdb"] = str(val).strip()
            break

    if not ids:
        return None
    return ExternalIds.model_validate(ids)


def _full_title_candidate(stem: str) -> Optional[str]:
    """A title candidate that keeps a " - Subtitle" / ": Subtitle" tail.

    guessit's ``title`` field sometimes drops everything after a
    " - "/": " separator (e.g. "The Lord of the Rings - The Two Towers
    (2002)" -> title "The Lord of the Rings"), which then fails to resolve
    even though the resolver matches the *full* title fine. This reuses the
    regex filename parser — which never splits on that separator — purely
    for its title-cleaning, independent of whatever guessit decided.
    """
    return _parse_video_filename(stem).title


def extract_signals(file: LocalMediaFile) -> Signals:
    """Build a ``Signals`` bag describing *file* for metadatarr resolution.

    VIDEO: ``guessit`` when available, else a regex filename fallback —
    then sharpened by embedded container metadata (title/date, via
    ``ffprobe``) when ``ffprobe`` is installed; see
    :func:`_apply_ffprobe_overrides`.
    MUSIC: embedded tags via ``mutagen`` when available, else a regex
    filename fallback ("Artist - Title" / "NN Title").
    """
    stem = file.path.stem
    if file.kind == "video":
        signals = _guessit_video_signals(file.path)
        if signals is None:
            signals = _parse_video_filename(stem)
        return _apply_ffprobe_overrides(signals, file.path)

    signals = _mutagen_music_signals(file.path)
    if signals is not None:
        return signals
    return _parse_music_filename(stem)


# ---------------------------------------------------------------------------
# Embedded id extraction (Radarr/Sonarr/Jellyfin filename conventions)
# ---------------------------------------------------------------------------

# ``{tmdb-696806}``, ``{tmdbid-696806}``, ``[tmdbid-696806]``, ``tmdb=696806``.
_TMDB_ID_RE = re.compile(r"[\[{]tmdb(?:id)?[-=](\d+)[\]}]", re.IGNORECASE)
# ``{imdb-tt1254207}``, ``[imdbid-tt1254207]``.
_IMDB_ID_RE = re.compile(r"[\[{]imdb(?:id)?[-=](tt\d+)[\]}]", re.IGNORECASE)
# ``{tvdb-12345}``, ``[tvdbid-12345]``.
_TVDB_ID_RE = re.compile(r"[\[{]tvdb(?:id)?[-=](\d+)[\]}]", re.IGNORECASE)


def extract_embedded_ids(name: str, *, is_true_episodic: bool = False) -> Optional[ExternalIds]:
    """Extract Radarr/Sonarr/Jellyfin-style embedded ids from *name*.

    *name* may be a bare filename or a full path — both the file's own
    name and any parent folder name commonly carry the id tag (Radarr
    puts it in the movie folder name, e.g.
    ``The Adam Project (2022) {tmdb-696806}/...mkv``), so callers should
    pass the fully joined string (``str(path)``) to catch both.

    Only well-delimited ``{...}``/``[...]`` tag forms are matched, to
    avoid false positives on incidental digit runs in a title/year.
    Returns ``None`` when no id tag is found.

    ``{tmdb-}``/``{tmdbid-}`` ids default to ``tmdb_movie`` (Radarr
    convention: Radarr, not Sonarr, is what stamps a bare ``tmdb-`` tag)
    and only map to ``tmdb_tv`` when *is_true_episodic* is set — callers
    must derive that from an **actual SxxEyy marker found in the
    filename**, never from a shaky type guess (e.g. guessit's ``type``
    field), because a purely numeric title like ``65 (2023)`` must
    resolve as ``tmdb_movie``, not ``tmdb_tv`` (see media-archivist
    PR #46). ``{tvdb-}`` always maps to ``tvdb`` (TV-only catalog by
    construction — Sonarr's convention).
    """
    ids: Dict[str, Any] = {}

    m = _TMDB_ID_RE.search(name)
    if m:
        ids["tmdb_tv" if is_true_episodic else "tmdb_movie"] = int(m.group(1))

    m = _IMDB_ID_RE.search(name)
    if m:
        ids["imdb"] = m.group(1)

    m = _TVDB_ID_RE.search(name)
    if m:
        ids["tvdb"] = int(m.group(1))

    if not ids:
        return None
    return ExternalIds.model_validate(ids)


# ---------------------------------------------------------------------------
# YouTube video-id extraction (yt-dlp / TubeArchivist / tubesync filenames)
# ---------------------------------------------------------------------------

# YouTube video ids are always exactly 11 chars from this alphabet.
_YT_ID_CHARS = "A-Za-z0-9_-"
_YT_ID_TOKEN = f"[{_YT_ID_CHARS}]{{11}}"
# ``Some Title [dQw4w9WgXcQ].mp4`` — yt-dlp's ``%(title)s [%(id)s].%(ext)s``.
# Anchored to the whole bracket so an 11-char *substring* of a longer/shorter
# release-tag bracket (``[Bluray-1080p]``, ``[Directors Cut]``) never matches:
# the bracket content must be *exactly* 11 id-alphabet chars, nothing else.
_YT_ID_BRACKET_RE = re.compile(r"\[(" + _YT_ID_TOKEN + r")\]")
# ``dQw4w9WgXcQ.mp4`` — TubeArchivist names the file after the bare id.
_YT_ID_BARE_RE = re.compile(r"^(" + _YT_ID_TOKEN + r")$")
# ``..._d558tMKjvgc_...`` — tubesync-style underscore-delimited id. Requires
# underscore boundaries on both sides so it never fires on an incidental
# 11-char run inside an ordinary title.
_YT_ID_UNDERSCORE_RE = re.compile(r"(?<=_)(" + _YT_ID_TOKEN + r")(?=_)")


def extract_youtube_id(name: str) -> Optional[str]:
    """Extract a yt-dlp/TubeArchivist/tubesync ``[VIDEOID]``-style YouTube id.

    *name* is a filename (basename or stem — an extension, if present, is
    stripped). Recognizes, most-specific first:

    - ``Title [VIDEOID].ext`` (yt-dlp's default ``%(id)s`` output template)
    - bare ``VIDEOID.ext`` (TubeArchivist)
    - ``..._VIDEOID_...`` underscore-delimited (tubesync)

    Deliberately conservative: a YouTube video id is *always* exactly 11
    characters from ``[A-Za-z0-9_-]``, so every pattern requires an exact
    11-char match at a well-delimited boundary — a release-tag bracket like
    ``[Bluray-1080p]`` (13 chars) or a 10/12-char bracketed string never
    matches. Returns ``None`` when nothing matches.
    """
    stem = Path(name).stem

    m = _YT_ID_BRACKET_RE.search(stem)
    if m:
        return m.group(1)

    m = _YT_ID_BARE_RE.match(stem)
    if m:
        return m.group(1)

    m = _YT_ID_UNDERSCORE_RE.search(stem)
    if m:
        return m.group(1)

    return None


def _enrich_from_tutubo(video_id: str) -> Optional[Dict[str, Any]]:
    """Best-effort real title/uploader/upload-date lookup for *video_id*.

    ``tutubo``'s public API (``Channel``/``Playlist``/``Video``) only lists
    videos *belonging to* a channel/playlist page — it has no
    fetch-a-single-video-by-id call. This reuses the same ``ytInitialData``
    parsing tutubo's own ``Channel._get_data``/``Channel.live`` use
    internally (``tutubo.transport.default_session`` + ``tutubo._utils.
    initial_data``) against the video's own watch page to recover
    ``videoDetails`` (title/author/publish date).

    # TODO: upstream a ``tutubo.channel.get_video(video_id)`` helper so
    # callers don't have to reach into these internals directly.

    Never raises: any failure (tutubo not installed, network, parsing) is
    swallowed and ``None`` is returned so the caller falls back to the
    filename-derived title.
    """
    try:
        from tutubo._utils import initial_data
        from tutubo.channel import _YT_COOKIES, _YT_HEADERS
        from tutubo.transport import default_session
    except ImportError:
        return None

    try:
        session = default_session()
        resp = session.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers=_YT_HEADERS, cookies=_YT_COOKIES, timeout=15,
        )
        resp.raise_for_status()
        data = initial_data(resp.text)
    except Exception:
        LOG.info("tutubo youtube enrich failed for %s", video_id, exc_info=True)
        return None

    details = data.get("videoDetails", {}) if isinstance(data, dict) else {}
    micro = (data.get("microformat", {}) or {}).get("playerMicroformatRenderer", {}) \
        if isinstance(data, dict) else {}

    title = details.get("title") or None
    author = details.get("author") or None
    upload_date = micro.get("uploadDate") or micro.get("publishDate")
    year = None
    if upload_date:
        m = re.match(r"(\d{4})", str(upload_date))
        if m:
            year = int(m.group(1))

    if not (title or author or year):
        return None
    return {"title": title, "artist": author, "year": year}


# ---------------------------------------------------------------------------
# Tagging
# ---------------------------------------------------------------------------

@dataclass
class TagResult:
    path: Path
    matched: bool
    external_ids: Optional[Dict[str, Any]]
    nfo_path: Optional[Path]
    action: Literal["wrote", "would-write", "skipped", "error"]
    note: str = ""
    # --rename outcome — always present, "off" when the feature isn't enabled.
    rename_action: Literal[
        "off", "renamed", "would-rename", "skipped-unmatched",
        "skipped-exists", "error",
    ] = "off"
    renamed_to: Optional[Path] = None
    # --write-tags outcome — always present, "off" when the feature isn't
    # enabled. See :func:`_write_music_tags`.
    tags_written: Literal[
        "off", "written", "would-write", "skipped-unmatched",
        "skipped-not-music", "error",
    ] = "off"
    tags_note: str = ""


# ---------------------------------------------------------------------------
# --write-tags (opt-in, destructive — embeds resolved metadata into the
# music file's OWN tags via mutagen, see tag_file's ``write_tags`` param)
# ---------------------------------------------------------------------------

# Standard MP4 "quicktime" atom names for the fields Easy* interfaces don't
# cover uniformly; freeform atoms (``----:...``) carry ISRC/MusicBrainz,
# which have no reserved iTunes atom.
_MP4_ATOM_MAP = {"title": "\xa9nam", "artist": "\xa9ART", "date": "\xa9day",
                 "genre": "\xa9gen"}


def _backup_tags_sidecar(path: Path, tags: Dict[str, Any]) -> None:
    """Dump *tags* (the file's tags BEFORE any write-tags modification) to
    a ``<file>.origtags.json`` sidecar, so a user can manually restore them.

    Best-effort and never clobbers an existing backup — only the very first
    write-tags pass over a file gets to record the pristine original.
    """
    backup_path = path.with_name(path.name + ".origtags.json")
    if backup_path.exists():
        return
    try:
        serializable = {
            str(k): ([str(v) for v in val] if isinstance(val, list) else str(val))
            for k, val in tags.items()
        }
        backup_path.write_text(json.dumps(serializable, indent=2, sort_keys=True),
                               encoding="utf-8")
    except OSError as exc:
        LOG.warning("write-tags: failed to write backup sidecar for %s: %s", path, exc)


def _write_music_tags(path: Path, *, fields: Dict[str, str],
                      isrc: Optional[str], mb_recording_id: Optional[str],
                      backup_tags: bool) -> None:
    """Write *fields* (plus ISRC / MusicBrainz recording id, when known)
    into *path*'s own tags via mutagen — ID3 for mp3, Vorbis comments for
    flac/ogg/opus, MP4 atoms (+ freeform atoms for isrc/mb id) for m4a.

    Only sets the fields given — never clears/clobbers unrelated existing
    tags. Raises on failure (caller wraps in try/except); mutagen's
    ``save()`` is format-safe, so a failure never leaves a half-written
    tag block.
    """
    ext = path.suffix.lower()

    if ext == ".mp3":
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3NoHeaderError

        try:
            audio = EasyID3(path)
        except ID3NoHeaderError:
            audio = _mutagen.File(path, easy=True)  # type: ignore[union-attr]
            audio.add_tags()
            audio = EasyID3(path)
        if backup_tags:
            _backup_tags_sidecar(path, dict(audio))
        for key, value in fields.items():
            audio[key] = value
        if isrc:
            audio["isrc"] = isrc
        if mb_recording_id:
            audio["musicbrainz_trackid"] = mb_recording_id
        audio.save()
        return

    if ext in (".m4a", ".mp4", ".m4b"):
        from mutagen.mp4 import MP4, MP4FreeForm

        audio = MP4(path)
        if backup_tags:
            _backup_tags_sidecar(path, dict(audio.tags or {}))
        for key, value in fields.items():
            atom = _MP4_ATOM_MAP.get(key)
            if atom:
                audio[atom] = [value]
        if isrc:
            audio["----:com.apple.iTunes:ISRC"] = [MP4FreeForm(isrc.encode("utf-8"))]
        if mb_recording_id:
            audio["----:com.apple.iTunes:MusicBrainz Track Id"] = [
                MP4FreeForm(mb_recording_id.encode("utf-8"))]
        audio.save()
        return

    # FLAC/OGG/OPUS and other Vorbis-comment formats: mutagen's generic
    # easy=True object already accepts arbitrary comment keys, no Easy*
    # wrapper (or its restricted key set) needed.
    audio = _mutagen.File(path, easy=True)  # type: ignore[union-attr]
    if audio is None:
        raise ValueError(f"mutagen could not identify audio format: {path}")
    if audio.tags is None:
        audio.add_tags()
    if backup_tags:
        _backup_tags_sidecar(path, dict(audio))
    for key, value in fields.items():
        audio[key] = value
    if isrc:
        audio["isrc"] = isrc
    if mb_recording_id:
        audio["musicbrainz_trackid"] = mb_recording_id
    audio.save()


def _write_tags_for_file(path: Path, *, media_kind: str, matched: bool,
                         signals: Signals, external_ids: Optional[Dict[str, Any]],
                         resolved_album: Optional[str], resolved_isrc: Optional[str],
                         dry_run: bool, backup_tags: bool) -> "tuple[str, str]":
    """Compute (and, unless *dry_run*, perform) writing resolved metadata
    into *path*'s own audio tags.

    Returns ``(tags_written_action, note)``. Never raises — any mutagen
    failure is captured as ``("error", str(exc))`` so one bad file never
    aborts a batch run.

    SAFETY (never relaxed):

    - Only ``media_kind == "music"`` files are ever considered — video/other
      files are always ``"skipped-not-music"``.
    - Only a CONFIDENT match (``matched=True``) is ever written — an
      unidentified file is never stamped with a guess
      (``"skipped-unmatched"``).
    - ``dry_run`` computes and reports the fields that WOULD be written
      (``"would-write"``) without opening/touching the file at all.
    - Never clobbers unrelated existing tags — only the resolved fields are
      set.
    """
    if media_kind != "music":
        return "skipped-not-music", ""
    if not matched:
        return "skipped-unmatched", ""
    if _mutagen is None:
        return "error", "mutagen is not installed (the '[tag]' extra)"

    fields: Dict[str, str] = {}
    if signals.title:
        fields["title"] = signals.title
    if signals.artist:
        fields["artist"] = signals.artist
    if signals.year is not None:
        fields["date"] = str(signals.year)
    if signals.content_genres:
        fields["genre"] = signals.content_genres[0]
    if resolved_album:
        fields["album"] = resolved_album

    mb_recording_id = (external_ids or {}).get("musicbrainz_recording")
    isrc = resolved_isrc or (external_ids or {}).get("isrc")

    written = sorted(fields.keys())
    if isrc:
        written.append("isrc")
    if mb_recording_id:
        written.append("musicbrainz_recording")

    if not written:
        return "skipped-unmatched", "no resolved metadata to write"

    note = ", ".join(written)
    if dry_run:
        return "would-write", note

    try:
        _write_music_tags(path, fields=fields, isrc=isrc,
                          mb_recording_id=mb_recording_id, backup_tags=backup_tags)
    except Exception as exc:
        LOG.exception("write-tags: failed to write tags for %s", path)
        return "error", str(exc)

    return "written", note


# ---------------------------------------------------------------------------
# Rename (opt-in, destructive — see tag_file's ``rename`` parameter)
# ---------------------------------------------------------------------------

# Windows/POSIX-illegal path characters plus control chars; kept conservative
# so a title survives round-tripping through any of the filesystems a
# Jellyfin/Kodi library might live on (NTFS, exFAT, ext4, ...).
_ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_name_component(text: str) -> str:
    """Strip filesystem-illegal characters from a single path component."""
    text = _ILLEGAL_CHARS_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "untitled"


def _tmdb_id_from_external_ids(external_ids: Optional[Dict[str, Any]]) -> Optional[int]:
    if not external_ids:
        return None
    return external_ids.get("tmdb_movie") or external_ids.get("tmdb_tv")


def build_rename_target(*, signals: Signals, media_kind: str,
                        external_ids: Optional[Dict[str, Any]],
                        ext: str, pattern: Optional[str] = None) -> str:
    """Build a sanitized target basename (incl. leading ``.``-extension).

    Built-in patterns, keyed by *media_kind* (Radarr/Jellyfin conventions):

    - ``movie``:    ``Title (Year) {tmdb-ID}.ext`` — ID omitted if unknown.
    - ``episodic``: ``Title (Year) {tmdb-ID}.ext``, or ``Title - SxxEyy.ext``
                    when a season/episode pair is known and no year/id is.
    - ``music``:    ``Artist - Title.ext``.

    *pattern*, when given, is a small ``{title}``/``{year}``/``{id}``/
    ``{artist}``/``{season}``/``{episode}`` format string — no full
    templating engine, just ``str.format`` over a fixed field set with each
    substituted value pre-sanitized.
    """
    title = _sanitize_name_component(signals.title or "untitled")
    year = signals.year
    tmdb_id = _tmdb_id_from_external_ids(external_ids)
    artist = _sanitize_name_component(signals.artist or "") if signals.artist else ""
    season = signals.season
    episode = signals.episode

    if pattern:
        fields = {
            "title": title,
            "year": year if year is not None else "",
            "id": tmdb_id if tmdb_id is not None else "",
            "artist": artist,
            "season": f"{season:02d}" if season is not None else "",
            "episode": f"{episode:02d}" if episode is not None else "",
        }
        try:
            base = pattern.format(**fields)
        except (KeyError, IndexError):
            base = title
        base = _sanitize_name_component(base)
        return f"{base}{ext}"

    if media_kind == "music":
        base = f"{artist} - {title}" if artist else title
        return f"{_sanitize_name_component(base)}{ext}"

    if media_kind == "episodic":
        if year is not None or tmdb_id is not None:
            year_part = f" ({year})" if year is not None else ""
            id_part = f" {{tmdb-{tmdb_id}}}" if tmdb_id is not None else ""
            base = f"{title}{year_part}{id_part}"
        elif season is not None and episode is not None:
            base = f"{title} - S{season:02d}E{episode:02d}"
        else:
            base = title
        return f"{_sanitize_name_component(base)}{ext}"

    # movie (default)
    year_part = f" ({year})" if year is not None else ""
    id_part = f" {{tmdb-{tmdb_id}}}" if tmdb_id is not None else ""
    base = f"{title}{year_part}{id_part}"
    return f"{_sanitize_name_component(base)}{ext}"


def _plan_rename_target(*, path: Path, signals: Signals, media_kind: str,
                        external_ids: Optional[Dict[str, Any]],
                        pattern: Optional[str], folderize: bool) -> Path:
    new_name = build_rename_target(
        signals=signals, media_kind=media_kind, external_ids=external_ids,
        ext=path.suffix, pattern=pattern,
    )
    if folderize:
        folder_name = _sanitize_name_component(
            f"{_sanitize_name_component(signals.title or 'untitled')}"
            + (f" ({signals.year})" if signals.year is not None else "")
        )
        return path.parent / folder_name / new_name
    return path.parent / new_name


DEFAULT_JOURNAL_NAME = ".metadatarr-rename-journal.jsonl"


def default_journal_path(root: str) -> Path:
    """Default rename-journal location: ``<root>/.metadatarr-rename-journal.jsonl``."""
    return Path(root) / DEFAULT_JOURNAL_NAME


def _append_journal_record(journal_path: Path, record: Dict[str, Any]) -> None:
    """Append one JSONL record to *journal_path*.

    Best-effort: a journal write failure is logged but must never fail the
    rename it's recording (the file has already been moved by the time
    this runs).
    """
    try:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with journal_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        LOG.warning("rename journal: failed to append to %s: %s", journal_path, exc)


def _move_atomic(src: Path, dst: Path) -> Optional[str]:
    """Move *src* -> *dst*, atomic within a filesystem.

    Returns ``None`` on success, or an error string on failure. Never
    partially moves: on a cross-filesystem rename (``OSError`` with
    ``errno.EXDEV``) the source is left untouched and an error is reported
    rather than falling back to copy+delete.
    """
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
    except OSError as exc:
        return str(exc)
    return None


def _apply_rename(*, path: Path, nfo_path: Optional[Path], matched: bool,
                  signals: Signals, media_kind: str,
                  external_ids: Optional[Dict[str, Any]],
                  dry_run: bool, rename_pattern: Optional[str],
                  rename_folder: bool,
                  journal_path: Optional[Path] = None) -> "tuple[str, Optional[Path]]":
    """Compute (and, unless dry_run, perform) the rename for one file.

    Returns ``(rename_action, renamed_to)``. Never touches the media file's
    content — only its name/location. Never raises: any move failure is
    captured as ``("error", None)``.

    When *journal_path* is given and a real (non-dry-run) move happens, one
    JSONL record is appended recording the media move (and the ``.nfo``
    move, if one happened) so it can later be undone — see
    :func:`undo_renames`. Dry-run and skipped/error outcomes are never
    journaled.
    """
    if not matched:
        return "skipped-unmatched", None

    target = _plan_rename_target(
        path=path, signals=signals, media_kind=media_kind,
        external_ids=external_ids, pattern=rename_pattern,
        folderize=rename_folder,
    )

    # already correctly named/placed — nothing to move.
    if target == path:
        return ("would-rename" if dry_run else "renamed"), target

    target_exists = False
    if target.exists():
        try:
            target_exists = not target.samefile(path)
        except OSError:
            target_exists = True
    if target_exists:
        return "skipped-exists", None

    if dry_run:
        return "would-rename", target

    error = _move_atomic(path, target)
    if error is not None:
        return "error", None

    moved_nfo_from: Optional[Path] = None
    moved_nfo_to: Optional[Path] = None
    if nfo_path is not None and nfo_path.exists():
        nfo_target = target.with_suffix(".nfo")
        if nfo_target.exists():
            try:
                same = nfo_target.samefile(nfo_path)
            except OSError:
                same = False
            if not same:
                # Media file already moved successfully; don't lose the nfo
                # (leave it where it is) but the media rename itself stands.
                LOG.warning(
                    "rename: nfo target %s already exists, leaving old nfo at %s",
                    nfo_target, nfo_path)
                if journal_path is not None:
                    _append_journal_record(journal_path, {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "old_path": str(path), "new_path": str(target),
                        "old_nfo": None, "new_nfo": None,
                    })
                return "renamed", target
        nfo_error = _move_atomic(nfo_path, nfo_target)
        if nfo_error is not None:
            LOG.warning("rename: failed to move nfo %s -> %s: %s",
                       nfo_path, nfo_target, nfo_error)
        else:
            moved_nfo_from, moved_nfo_to = nfo_path, nfo_target

    if journal_path is not None:
        _append_journal_record(journal_path, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "old_path": str(path), "new_path": str(target),
            "old_nfo": str(moved_nfo_from) if moved_nfo_from else None,
            "new_nfo": str(moved_nfo_to) if moved_nfo_to else None,
        })

    return "renamed", target


def _media_kind(signals: Signals) -> str:
    if signals.medium == MediaType.MUSIC:
        return "music"
    if signals.medium == MediaType.EPISODIC_SERIES or (
        signals.season is not None or signals.episode is not None
    ):
        return "episodic"
    return "movie"


def tag_file(file: LocalMediaFile, *, write_nfo: bool = True,
            dry_run: bool = False, min_confidence: float = 0.5,
            rename: bool = False, rename_pattern: Optional[str] = None,
            rename_folder: bool = False, incremental: bool = False,
            force: bool = False,
            rename_journal: Optional[Path] = None,
            write_tags: bool = False, backup_tags: bool = False) -> TagResult:
    """Resolve *file* via metadatarr and write (or preview) its ``.nfo``.

    Never raises: any failure to read/resolve the file is captured in the
    returned :class:`TagResult` (``action="error"``) so a bad file never
    aborts a batch run.

    ``rename`` (default ``False``, opt-in) additionally renames/moves the
    media file — and its ``.nfo`` sidecar, if any — to a clean
    Radarr/Jellyfin-style name built from the RESOLVED metadata; see
    :func:`build_rename_target`. Safety rules (never relaxed):

    - Only a CONFIDENT match (``matched=True``) is ever renamed — a
      filename-only guess never moves a file the run couldn't identify.
    - ``dry_run`` still applies: the planned rename is computed and
      reported via ``rename_action="would-rename"``/``renamed_to``, but
      nothing is moved.
    - Collision-safe: an existing, different file at the target path is
      never overwritten (``rename_action="skipped-exists"``).
    - Atomic within a filesystem (``os.replace``); a cross-filesystem move
      is reported as an error rather than partially completed.
    - Never edits file *content* — only name/location.

    ``incremental`` (default ``False``, opt-in) makes re-running over a
    huge library fast: a file already considered "tagged" is skipped
    WITHOUT resolving — no :func:`~metadatarr.resolve.resolve`/
    :func:`~metadatarr.resolve.enrich` call, no network — which is the
    whole point for 40k+ file libraries. "Already tagged" means a sibling
    ``.nfo`` already exists (only checked when ``write_nfo`` is on); when
    ``rename`` is also on, the file's name must additionally already carry
    an embedded catalog id (``{tmdb-...}``/``{imdb-...}``/``{tvdb-...}``,
    see :func:`extract_embedded_ids`) — a cheap, resolve-free proxy for
    "already matches the rename target" — otherwise it's still considered
    unfinished and is (re)processed normally. ``force`` (default ``False``)
    overrides ``incremental`` and always re-tags, even when a sidecar
    exists; ``force`` beats ``incremental``.

    ``write_tags`` (default ``False``, opt-in and DESTRUCTIVE — it modifies
    the media file's own tag block) additionally embeds the resolved
    metadata (title/artist/date/genre/album, plus ISRC and MusicBrainz
    recording id when known) into the audio file's native tags via
    mutagen, so it travels with the file to any player — not just the
    ``.nfo``. MUSIC ONLY; a video file is always
    ``tags_written="skipped-not-music"``. Safety rules (never relaxed):

    - Only a CONFIDENT match (``matched=True``) is ever written — an
      unidentified file's tags are left untouched
      (``tags_written="skipped-unmatched"``).
    - ``dry_run`` still applies: the fields that would be written are
      computed and reported (``tags_written="would-write"``,
      ``tags_note``), but the file is never opened for writing.
    - Never clobbers unrelated existing tags — only the resolved fields
      are set.
    - Never raises: a mutagen failure is captured as
      ``tags_written="error"`` so one bad file never aborts a batch run.
    - ``backup_tags`` (default ``False``): before the FIRST write-tags
      modification of a file, dump its pre-write tags to a
      ``<file>.origtags.json`` sidecar so they can be manually restored.
      Off by default to avoid littering the library with sidecars on
      every run; opt in for extra safety on a first pass.
    - Composes with ``write_nfo``: run with both, or ``write_nfo=False,
      write_tags=True`` to embed metadata only, with no ``.nfo``.
    """
    nfo_path = file.path.with_suffix(".nfo")
    if incremental and not force and write_nfo and nfo_path.exists():
        already_done = True
        if rename and extract_embedded_ids(str(file.path)) is None:
            already_done = False
        if already_done:
            return TagResult(
                path=file.path, matched=False, external_ids=None,
                nfo_path=nfo_path, action="skipped",
                note="already tagged (incremental)",
                rename_action="skipped-exists" if rename else "off",
            )

    try:
        signals = extract_signals(file)
    except Exception as exc:  # pragma: no cover — defensive, extractors are safe
        LOG.exception("failed to extract signals for %s", file.path)
        return TagResult(path=file.path, matched=False, external_ids=None,
                         nfo_path=None, action="error", note=str(exc))

    external_ids: Optional[Dict[str, Any]] = None
    matched = False
    note = ""
    # Populated only by the audio-fingerprint (Shazam) fallback below, which
    # is the one source that hands back an album/ISRC directly — Signals has
    # no album field, and other match paths don't surface ISRC. Feeds
    # write_tags (see _write_tags_for_file).
    resolved_album: Optional[str] = None
    resolved_isrc: Optional[str] = None

    # A "real" SxxEyy marker in the filename itself — never guessit's type
    # guess — is the only thing allowed to route a bare {tmdb-} tag to
    # tmdb_tv instead of the Radarr-convention default tmdb_movie.
    is_true_episodic = bool(_SXXEXX_RE.search(file.path.stem))
    seed_ids = extract_embedded_ids(str(file.path), is_true_episodic=is_true_episodic)
    if seed_ids is None and file.kind == "video":
        # No id in the filename — Radarr/Jellyfin sometimes stamp one into
        # the container instead. Optional, ffprobe-gated (see
        # `_ffprobe_tags`): silently {} when ffprobe is absent or the file
        # carries no such tag.
        seed_ids = _embedded_ids_from_tags(
            _ffprobe_tags(file.path), is_true_episodic=is_true_episodic)

    # No Radarr/Sonarr/Jellyfin catalog id -> check for a yt-dlp/
    # TubeArchivist/tubesync ``[VIDEOID]``-style filename. A catalog id
    # (checked above) always wins: YouTube content isn't in tmdb/imdb/tvdb,
    # so the YouTube video id is only used as a last resort before the
    # generic title/year resolver.
    youtube_id = extract_youtube_id(file.path.name) if seed_ids is None else None

    if seed_ids is not None:
        # Authoritative: an id embedded by Radarr/Sonarr/Jellyfin beats a
        # title/year guess. Skip resolve() entirely and try to expand the
        # seed into the full cross-catalog id set; fall back to the raw
        # seed id (still authoritative on its own) if that fails.
        seed_dict = {
            k: v for k, v in seed_ids.model_dump().items()
            if v and k != "extra"
        }
        external_ids = seed_dict
        matched = True
        note = "matched (embedded id)"
        try:
            expanded = enrich(seed_ids, medium=signals.medium)
            expanded_dict = {
                k: v for k, v in expanded.model_dump().items()
                if v and k != "extra"
            }
            if expanded_dict:
                external_ids = expanded_dict
        except Exception as exc:
            LOG.warning("metadatarr enrich failed for %s: %s", file.path, exc)
    elif youtube_id is not None:
        # The YouTube video id IS the canonical id for YouTube-sourced
        # content — it's never in tmdb/imdb/tvdb. mediavocab's ExternalIds
        # model has no dedicated video-id field yet (only
        # ``youtube_channel_id``), so it's carried in the free-form
        # ``extra`` dict.
        # TODO: add a ``youtube_video`` field to mediavocab.ExternalIds.
        external_ids = {"extra": {"youtube": youtube_id}}
        matched = True
        note = "matched (youtube id)"
        # Optional: real title/uploader/upload-year via tutubo, in addition
        # to (never instead of) the id — a network/parsing failure here
        # must never downgrade the match, only skip the nicer title.
        try:
            enriched = _enrich_from_tutubo(youtube_id)
        except Exception as exc:  # pragma: no cover — defensive belt+braces
            LOG.info("youtube enrich failed for %s: %s", file.path, exc)
            enriched = None
        if enriched:
            updates = {k: v for k, v in enriched.items() if v}
            if updates:
                signals = signals.model_copy(update=updates)
    else:
        original_title = signals.title
        try:
            result = resolve(signals)
            if result.signals is not None and result.external_ids is not None:
                ids_dict = {
                    k: v for k, v in result.external_ids.model_dump().items()
                    if v and k != "extra"
                }
                if ids_dict:
                    external_ids = ids_dict
                    matched = True
                    signals = result.signals
        except Exception as exc:
            # A provider failure (network, missing key, bad response) must
            # never abort the run — fall through and write a filename-only
            # nfo.
            LOG.warning("metadatarr resolve failed for %s: %s", file.path, exc)
            note = f"resolve failed: {exc}"

        # Subtitle-truncation fallback (bounded to one extra resolve() call):
        # guessit can drop a " - Subtitle" tail from the title (e.g. "The
        # Lord of the Rings - The Two Towers (2002)" -> title "The Lord of
        # the Rings"), which then fails to resolve even though the full
        # title matches fine. Retry once against the fuller title — derived
        # independently from the filename, see `_full_title_candidate` — only
        # when the first attempt found nothing.
        if not matched and file.kind == "video":
            alt_title = _full_title_candidate(file.path.stem)
            if alt_title and alt_title != original_title:
                alt_signals = signals.model_copy(update={"title": alt_title})
                try:
                    alt_result = resolve(alt_signals)
                    if alt_result.signals is not None and alt_result.external_ids is not None:
                        alt_ids_dict = {
                            k: v for k, v in alt_result.external_ids.model_dump().items()
                            if v and k != "extra"
                        }
                        if alt_ids_dict:
                            external_ids = alt_ids_dict
                            matched = True
                            signals = alt_result.signals
                            note = "matched (full-title retry)"
                except Exception as exc:
                    LOG.warning(
                        "metadatarr resolve (full-title retry) failed for %s: %s",
                        file.path, exc)

        # Music fingerprint fallback: a music file that couldn't be matched by
        # embedded tags / filename (obscure or mistagged) can often still be
        # identified from the audio itself via Shazam (metadatarr.identify).
        # Optional — only runs when the ``[identify]`` extra (xazam) is
        # installed; any failure degrades silently to a filename-only nfo.
        if not matched and file.kind == "music":
            try:
                from metadatarr.identify import identify_audio
            except ImportError:
                identify_audio = None  # type: ignore[assignment]
            if identify_audio is not None:
                try:
                    am = identify_audio(str(file.path))
                    if am.matched:
                        dumped = (am.external_ids.model_dump()
                                  if am.external_ids is not None else {})
                        am_ids = {k: v for k, v in dumped.items()
                                  if v and k != "extra"}
                        if am_ids or am.signals is not None:
                            external_ids = am_ids
                            matched = True
                            if am.signals is not None:
                                signals = am.signals
                            note = "matched (audio fingerprint)"
                            resolved_album = am.album or None
                            resolved_isrc = am.isrc
                except Exception as exc:
                    LOG.info("audio fingerprint identify failed for %s: %s",
                             file.path, exc)

    media_kind = _media_kind(signals)

    if not signals.title:
        tags_written, tags_note = (
            _write_tags_for_file(
                file.path, media_kind=media_kind, matched=matched,
                signals=signals, external_ids=external_ids,
                resolved_album=resolved_album, resolved_isrc=resolved_isrc,
                dry_run=dry_run, backup_tags=backup_tags,
            ) if write_tags else ("off", "")
        )
        return TagResult(path=file.path, matched=False, external_ids=None,
                         nfo_path=None, action="skipped",
                         note=note or "no title could be determined",
                         tags_written=tags_written, tags_note=tags_note)

    def _do_rename(nfo_path_for_rename: Optional[Path]) -> "tuple[str, Optional[Path]]":
        if not rename:
            return "off", None
        return _apply_rename(
            path=file.path, nfo_path=nfo_path_for_rename, matched=matched,
            signals=signals, media_kind=media_kind, external_ids=external_ids,
            dry_run=dry_run, rename_pattern=rename_pattern,
            rename_folder=rename_folder, journal_path=rename_journal,
        )

    def _do_write_tags() -> "tuple[str, str]":
        if not write_tags:
            return "off", ""
        return _write_tags_for_file(
            file.path, media_kind=media_kind, matched=matched,
            signals=signals, external_ids=external_ids,
            resolved_album=resolved_album, resolved_isrc=resolved_isrc,
            dry_run=dry_run, backup_tags=backup_tags,
        )

    if not write_nfo:
        rename_action, renamed_to = _do_rename(None)
        tags_written, tags_note = _do_write_tags()
        return TagResult(path=file.path, matched=matched,
                         external_ids=external_ids, nfo_path=None,
                         action="skipped", note=note or "--no-nfo",
                         rename_action=rename_action, renamed_to=renamed_to,
                         tags_written=tags_written, tags_note=tags_note)

    if dry_run:
        rename_action, renamed_to = _do_rename(nfo_path if nfo_path.exists() else None)
        tags_written, tags_note = _do_write_tags()
        return TagResult(path=file.path, matched=matched,
                         external_ids=external_ids, nfo_path=nfo_path,
                         action="would-write",
                         note=note or ("matched" if matched else "filename-only"),
                         rename_action=rename_action, renamed_to=renamed_to,
                         tags_written=tags_written, tags_note=tags_note)

    try:
        ext_ids_model = ExternalIds.model_validate(external_ids) if external_ids else None
        xml = nfo_xml(
            title=signals.title,
            year=signals.year,
            media_kind=media_kind,
            external_ids=ext_ids_model,
            artist=signals.artist,
            runtime=signals.runtime,
            season=signals.season,
            episode=signals.episode,
        )
        nfo_path.write_text(xml, encoding="utf-8")
    except Exception as exc:
        LOG.exception("failed to write nfo for %s", file.path)
        tags_written, tags_note = _do_write_tags()
        return TagResult(path=file.path, matched=matched,
                         external_ids=external_ids, nfo_path=None,
                         action="error", note=str(exc),
                         tags_written=tags_written, tags_note=tags_note)

    rename_action, renamed_to = _do_rename(nfo_path)
    tags_written, tags_note = _do_write_tags()
    final_nfo_path = renamed_to.with_suffix(".nfo") if (
        rename_action == "renamed" and renamed_to is not None) else nfo_path

    return TagResult(path=file.path, matched=matched, external_ids=external_ids,
                     nfo_path=final_nfo_path, action="wrote",
                     note=note or ("matched" if matched else "filename-only"),
                     rename_action=rename_action, renamed_to=renamed_to,
                     tags_written=tags_written, tags_note=tags_note)


def tag_library(root: str, *, media: str = "both", write_nfo: bool = True,
                dry_run: bool = False, min_confidence: float = 0.5,
                skip_extras: bool = True,
                rename: bool = False, rename_pattern: Optional[str] = None,
                rename_folder: bool = False,
                incremental: bool = False, force: bool = False,
                stats: Optional[Dict[str, int]] = None,
                rename_journal: Optional[str] = None,
                write_tags: bool = False, backup_tags: bool = False) -> List[TagResult]:
    """Scan *root* and tag every discovered media file.

    ``skip_extras`` (default ``True``) excludes Jellyfin/Kodi local-extras
    (trailers, samples, behind-the-scenes, etc) from the scan — see
    :func:`scan`. Pass a ``stats`` dict to have the number of skipped
    extras recorded under its ``"skipped_extras"`` key, for summary
    reporting.

    ``rename`` (default ``False``, opt-in and DESTRUCTIVE — it moves user
    files) additionally renames/organizes each confidently-matched file;
    see :func:`tag_file` for the full safety contract.

    ``incremental`` (default ``False``) skips already-tagged files
    without resolving/enriching (no network) — see :func:`tag_file`. A
    ``stats`` dict, if given, has the number of such skips recorded under
    ``"skipped_existing"``. ``force`` (default ``False``) always re-tags,
    overriding ``incremental``.

    Future enhancement (not implemented here): for music files whose
    filename/tags give :func:`tag_file` nothing useful to search on, this
    could fall back to :func:`metadatarr.identify.identify_audio` (Shazam
    fingerprint match via the optional ``xazam`` client) to recover a
    title/artist to resolve against.

    ``write_tags`` (default ``False``, opt-in and DESTRUCTIVE — it modifies
    music files' own tags) additionally embeds resolved metadata into each
    confidently-matched MUSIC file's own tags via mutagen; see
    :func:`tag_file` for the full safety contract (dry-run preview,
    confident-match-only, no clobbering unrelated tags). ``backup_tags``
    (default ``False``) writes a ``<file>.origtags.json`` sidecar with the
    pre-write tags before the first modification of each file.
    """
    journal_path = None
    if rename and not dry_run:
        journal_path = Path(rename_journal) if rename_journal else default_journal_path(root)

    results: List[TagResult] = []
    for file in scan(root, media=media, skip_extras=skip_extras, stats=stats):
        result = tag_file(file, write_nfo=write_nfo, dry_run=dry_run,
                          min_confidence=min_confidence,
                          rename=rename, rename_pattern=rename_pattern,
                          rename_folder=rename_folder,
                          incremental=incremental, force=force,
                          rename_journal=journal_path,
                          write_tags=write_tags, backup_tags=backup_tags)
        if incremental and result.note == "already tagged (incremental)" and stats is not None:
            stats["skipped_existing"] = stats.get("skipped_existing", 0) + 1
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# watch (poll a library on an interval, incrementally tagging new files)
# ---------------------------------------------------------------------------

def watch_library(root: str, *, interval: float, media: str = "both",
                  write_nfo: bool = True, min_confidence: float = 0.5,
                  skip_extras: bool = True,
                  rename: bool = False, rename_pattern: Optional[str] = None,
                  rename_folder: bool = False,
                  rename_journal: Optional[str] = None,
                  stop_event: Optional[threading.Event] = None,
                  on_cycle: Optional[Any] = None) -> Dict[str, int]:
    """Poll *root* every ``interval`` seconds, tagging only new/untagged files.

    Each cycle runs :func:`tag_library` with ``incremental=True`` (and
    ``dry_run=False``) so already-tagged files are skipped without any
    network access — a cycle over a huge, mostly-already-tagged library is
    cheap, and network cost is spent only on files that landed since the
    last cycle. This makes a "watch folder" self-maintaining library
    practical to run continuously (e.g. under systemd or in a docker
    container), without pulling in a filesystem-event dependency such as
    ``watchdog``/inotify — a plain polling loop reusing ``--incremental``
    is dependency-free and good enough for this use case. (A future
    enhancement could swap the sleep loop for real filesystem-event
    watching via ``watchdog`` if sub-second latency is ever needed.)

    A single cycle's exception is caught, logged, and never propagates —
    one bad cycle (e.g. a transient network error) must not kill the
    daemon. ``stop_event`` (a :class:`threading.Event`), if given, is
    waited on between cycles so the loop can be stopped promptly (e.g. on
    SIGINT) instead of sleeping the full interval; the loop also checks it
    before starting each cycle. ``on_cycle``, if given, is called after
    every cycle with a per-cycle stats dict (``tagged``, ``skipped_existing``,
    ``skipped_extras``, ``errors``).

    Returns accumulated totals across all cycles once the loop stops.
    """
    if stop_event is None:
        stop_event = threading.Event()

    totals: Dict[str, int] = {
        "cycles": 0, "tagged": 0, "skipped_existing": 0,
        "skipped_extras": 0, "errors": 0,
    }

    LOG.info("watch: starting on %s (interval=%ss)", root, interval)
    while not stop_event.is_set():
        cycle_stats: Dict[str, int] = {}
        try:
            results = tag_library(
                root, media=media, write_nfo=write_nfo, dry_run=False,
                min_confidence=min_confidence, skip_extras=skip_extras,
                rename=rename, rename_pattern=rename_pattern,
                rename_folder=rename_folder,
                incremental=True, force=False,
                stats=cycle_stats, rename_journal=rename_journal,
            )
            tagged = sum(1 for r in results if r.action == "wrote")
            errors = sum(1 for r in results if r.action == "error")
            cycle_stats["tagged"] = tagged
            cycle_stats["errors"] = errors
            totals["cycles"] += 1
            totals["tagged"] += tagged
            totals["errors"] += errors
            totals["skipped_existing"] += cycle_stats.get("skipped_existing", 0)
            totals["skipped_extras"] += cycle_stats.get("skipped_extras", 0)
            LOG.info(
                "watch: cycle %d done — tagged=%d skipped-existing=%d errors=%d",
                totals["cycles"], tagged,
                cycle_stats.get("skipped_existing", 0), errors,
            )
        except Exception:  # noqa: BLE001 - a cycle must never kill the loop
            LOG.exception("watch: cycle failed, will retry next interval")
            cycle_stats.setdefault("errors", 1)
            totals["errors"] += 1

        if on_cycle is not None:
            on_cycle(cycle_stats)

        if stop_event.wait(interval):
            break

    LOG.info("watch: stopped after %d cycle(s)", totals["cycles"])
    return totals


# ---------------------------------------------------------------------------
# Undo (reverse a --rename run from its journal)
# ---------------------------------------------------------------------------

@dataclass
class UndoResult:
    reversed: int = 0
    skipped_exists: int = 0
    skipped_missing: int = 0
    errors: int = 0
    details: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.details is None:
            self.details = []


def _read_journal(journal_path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not journal_path.exists():
        return records
    with journal_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                LOG.warning("rename journal: skipping malformed line in %s", journal_path)
    return records


def _write_journal(journal_path: Path, records: List[Dict[str, Any]]) -> None:
    if not records:
        # Nothing left to undo — remove the journal rather than leave an
        # empty file behind.
        try:
            journal_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            LOG.warning("rename journal: failed to remove %s: %s", journal_path, exc)
        return
    try:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with journal_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        LOG.warning("rename journal: failed to rewrite %s: %s", journal_path, exc)


def undo_renames(root: str, *, journal_path: Optional[str] = None,
                 dry_run: bool = False) -> UndoResult:
    """Reverse the moves recorded in a ``--rename`` run's journal.

    Processes journal records most-recent-first. For each record, moves
    ``new_path`` back to ``old_path`` (and ``new_nfo`` back to ``old_nfo``,
    if the record has one). Never raises.

    Safety rules (never relaxed):

    - Collision-safe: if ``old_path`` already exists, the record is
      skipped (``skipped_exists``) rather than overwriting whatever is
      there now.
    - If ``new_path`` no longer exists (already moved or deleted outside
      metadatarr), the record is skipped (``skipped_missing``).
    - Moves are atomic within a filesystem (:func:`_move_atomic`); a
      cross-filesystem move is reported as an error and the record is left
      in the journal so it can be retried.
    - ``dry_run`` previews the reversal (what would move where) without
      touching anything, and never rewrites the journal.
    - A successfully-undone record is removed from the journal on
      completion so re-running ``--undo-rename`` never double-applies it.
    """
    jpath = Path(journal_path) if journal_path else default_journal_path(root)
    result = UndoResult()
    records = _read_journal(jpath)
    if not records:
        result.details.append(f"no journal records found at {jpath}")
        return result

    remaining: List[Dict[str, Any]] = []
    # Most-recent-first.
    for record in reversed(records):
        old_path = Path(record["old_path"])
        new_path = Path(record["new_path"])
        old_nfo = Path(record["old_nfo"]) if record.get("old_nfo") else None
        new_nfo = Path(record["new_nfo"]) if record.get("new_nfo") else None

        if not new_path.exists():
            result.skipped_missing += 1
            result.details.append(f"skip (missing): {new_path} no longer exists")
            remaining.append(record)
            continue

        if old_path.exists():
            try:
                same = old_path.samefile(new_path)
            except OSError:
                same = False
            if not same:
                result.skipped_exists += 1
                result.details.append(f"skip (exists): {old_path} is occupied")
                remaining.append(record)
                continue

        if dry_run:
            result.reversed += 1
            result.details.append(f"would move: {new_path} -> {old_path}")
            remaining.append(record)
            continue

        error = _move_atomic(new_path, old_path)
        if error is not None:
            result.errors += 1
            result.details.append(f"error moving {new_path} -> {old_path}: {error}")
            remaining.append(record)
            continue

        if new_nfo is not None and old_nfo is not None and new_nfo.exists():
            nfo_error = _move_atomic(new_nfo, old_nfo)
            if nfo_error is not None:
                LOG.warning("undo: failed to move nfo %s -> %s: %s",
                           new_nfo, old_nfo, nfo_error)
                result.details.append(
                    f"warning: nfo {new_nfo} -> {old_nfo} failed: {nfo_error}")

        result.reversed += 1
        result.details.append(f"reversed: {new_path} -> {old_path}")
        # record fully undone -> dropped from the journal.

    if not dry_run:
        # Restore chronological order for whatever's left.
        _write_journal(jpath, list(reversed(remaining)))

    return result
