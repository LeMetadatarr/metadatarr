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
from dataclasses import dataclass
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
                  rename_folder: bool) -> "tuple[str, Optional[Path]]":
    """Compute (and, unless dry_run, perform) the rename for one file.

    Returns ``(rename_action, renamed_to)``. Never touches the media file's
    content — only its name/location. Never raises: any move failure is
    captured as ``("error", None)``.
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
                return "renamed", target
        nfo_error = _move_atomic(nfo_path, nfo_target)
        if nfo_error is not None:
            LOG.warning("rename: failed to move nfo %s -> %s: %s",
                       nfo_path, nfo_target, nfo_error)

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
            rename_folder: bool = False) -> TagResult:
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
    """
    try:
        signals = extract_signals(file)
    except Exception as exc:  # pragma: no cover — defensive, extractors are safe
        LOG.exception("failed to extract signals for %s", file.path)
        return TagResult(path=file.path, matched=False, external_ids=None,
                         nfo_path=None, action="error", note=str(exc))

    external_ids: Optional[Dict[str, Any]] = None
    matched = False
    note = ""

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
                except Exception as exc:
                    LOG.info("audio fingerprint identify failed for %s: %s",
                             file.path, exc)

    if not signals.title:
        return TagResult(path=file.path, matched=False, external_ids=None,
                         nfo_path=None, action="skipped",
                         note=note or "no title could be determined")

    media_kind = _media_kind(signals)

    def _do_rename(nfo_path_for_rename: Optional[Path]) -> "tuple[str, Optional[Path]]":
        if not rename:
            return "off", None
        return _apply_rename(
            path=file.path, nfo_path=nfo_path_for_rename, matched=matched,
            signals=signals, media_kind=media_kind, external_ids=external_ids,
            dry_run=dry_run, rename_pattern=rename_pattern,
            rename_folder=rename_folder,
        )

    nfo_path = file.path.with_suffix(".nfo")

    if not write_nfo:
        rename_action, renamed_to = _do_rename(None)
        return TagResult(path=file.path, matched=matched,
                         external_ids=external_ids, nfo_path=None,
                         action="skipped", note=note or "--no-nfo",
                         rename_action=rename_action, renamed_to=renamed_to)

    if dry_run:
        rename_action, renamed_to = _do_rename(nfo_path if nfo_path.exists() else None)
        return TagResult(path=file.path, matched=matched,
                         external_ids=external_ids, nfo_path=nfo_path,
                         action="would-write",
                         note=note or ("matched" if matched else "filename-only"),
                         rename_action=rename_action, renamed_to=renamed_to)

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
        return TagResult(path=file.path, matched=matched,
                         external_ids=external_ids, nfo_path=None,
                         action="error", note=str(exc))

    rename_action, renamed_to = _do_rename(nfo_path)
    final_nfo_path = renamed_to.with_suffix(".nfo") if (
        rename_action == "renamed" and renamed_to is not None) else nfo_path

    return TagResult(path=file.path, matched=matched, external_ids=external_ids,
                     nfo_path=final_nfo_path, action="wrote",
                     note=note or ("matched" if matched else "filename-only"),
                     rename_action=rename_action, renamed_to=renamed_to)


def tag_library(root: str, *, media: str = "both", write_nfo: bool = True,
                dry_run: bool = False, min_confidence: float = 0.5,
                skip_extras: bool = True,
                rename: bool = False, rename_pattern: Optional[str] = None,
                rename_folder: bool = False,
                stats: Optional[Dict[str, int]] = None) -> List[TagResult]:
    """Scan *root* and tag every discovered media file.

    ``skip_extras`` (default ``True``) excludes Jellyfin/Kodi local-extras
    (trailers, samples, behind-the-scenes, etc) from the scan — see
    :func:`scan`. Pass a ``stats`` dict to have the number of skipped
    extras recorded under its ``"skipped_extras"`` key, for summary
    reporting.

    ``rename`` (default ``False``, opt-in and DESTRUCTIVE — it moves user
    files) additionally renames/organizes each confidently-matched file;
    see :func:`tag_file` for the full safety contract.

    Future enhancement (not implemented here): for music files whose
    filename/tags give :func:`tag_file` nothing useful to search on, this
    could fall back to :func:`metadatarr.identify.identify_audio` (Shazam
    fingerprint match via the optional ``xazam`` client) to recover a
    title/artist to resolve against.
    """
    results: List[TagResult] = []
    for file in scan(root, media=media, skip_extras=skip_extras, stats=stats):
        result = tag_file(file, write_nfo=write_nfo, dry_run=dry_run,
                          min_confidence=min_confidence,
                          rename=rename, rename_pattern=rename_pattern,
                          rename_folder=rename_folder)
        results.append(result)
    return results
