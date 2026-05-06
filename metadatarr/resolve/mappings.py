"""User-defined and package-level cross-platform identity mappings.

Some entities are the same artist / album / label across platforms but there
is no shared authoritative ID — the only way to know is to assert it
explicitly.  This module loads those assertions from two TOML files:

1. **Package-level** — ``metadatarr/data/mappings.toml``, shipped with the
   package and maintained by the community.
2. **User-level** — ``$XDG_CONFIG_HOME/metadatarr/mappings.toml`` (defaulting to
   ``~/.config/metadatarr/mappings.toml``).  Loaded second; user entries that
   share an identifier with a package entry extend it (more IDs are merged
   in); otherwise they add a new entry.

File format — TOML, one section per entity::

    [[artist]]
    name = "Acidkid / Piratech"                        # display only
    soundcloud_artist_url = "https://soundcloud.com/acidkid"
    bandcamp_artist_url   = "https://piratech.bandcamp.com/"

    [[artist]]
    name = "Some Band"
    bandcamp_band_id        = "12345678"
    soundcloud_user_id      = "987654"
    musicbrainz_artist      = "some-mbid-uuid"

Every key except ``name`` is treated as an identifier.  Keys must match
field names in :class:`~mediavocab.models.ExternalIds` or any
``extra.*`` key a provider emits.

``apply_mappings(role, external_ids)`` enriches an :class:`ExternalIds`
instance with any mapping entries that share at least one identifier with it.
Call this after consolidating provider matches to merge cross-platform IDs
the providers themselves could never link.
"""
from __future__ import annotations

import os
import sys
import threading
from importlib import resources
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from metadatarr.resolve.entities import EntityRole
from mediavocab.models import ExternalIds

# ---------------------------------------------------------------------------
# TOML loading — stdlib tomllib (3.11+) or tomli shim
# ---------------------------------------------------------------------------

try:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore[no-redef]
    _TOML_AVAILABLE = True
except ImportError:
    _TOML_AVAILABLE = False


# ---------------------------------------------------------------------------
# URL normalisation — strip scheme/trailing-slash noise for comparison
# ---------------------------------------------------------------------------

def _norm(value: str) -> str:
    """Normalise an identifier value for index lookup."""
    v = value.strip()
    if "://" in v:
        # For URLs: lowercase host, strip trailing slash from path
        parts = urlsplit(v)
        path = parts.path.rstrip("/")
        v = f"{parts.scheme}://{parts.netloc.lower()}{path}"
    return v


# ---------------------------------------------------------------------------
# Mapping entry
# ---------------------------------------------------------------------------

_SKIP_KEYS = {"name"}
# Keys whose values are platform URLs (used to match against url-type extras)
_URL_KEYS = {
    "bandcamp_artist_url", "bandcamp_track_url", "bandcamp_album_url",
    "soundcloud_artist_url", "soundcloud_track_url",
    "youtube_channel_url", "youtube_video_url",
    "stream_url",
}
# ExternalIds first-class field names (everything except `extra`)
_FIRST_CLASS = {
    f for f in ExternalIds.model_fields if f != "extra"
}


class MappingEntry:
    """One asserted identity cluster: a set of (key, value) identifiers that
    all refer to the same entity.

    ``score`` (range ``0.0``–``1.0``) lets you ship probabilistic mappings —
    e.g. a fuzzy-matched candidate from a future Wikidata-seeding pass — at
    a lower confidence than the hand-curated TOML defaults (``1.0``).
    Consumers can filter on ``score`` before applying.
    """

    __slots__ = ("role", "name", "identifiers", "score")

    def __init__(self, role: EntityRole, name: Optional[str],
                 identifiers: Dict[str, str],
                 score: float = 1.0) -> None:
        self.role = role
        self.name = name
        # Normalise all values at load time so comparisons are cheap.
        self.identifiers: Dict[str, str] = {
            k: _norm(v) for k, v in identifiers.items()
        }
        self.score = max(0.0, min(score, 1.0))

    def to_external_ids(self) -> ExternalIds:
        """Convert this entry's identifiers into an :class:`ExternalIds`."""
        first_class: dict = {}
        extra: dict = {}
        for k, v in self.identifiers.items():
            if k in _FIRST_CLASS:
                field = ExternalIds.model_fields[k]
                annotation = field.annotation
                # Coerce to int if the field expects an integer.
                try:
                    if annotation in (Optional[int], int):  # type: ignore[misc]
                        first_class[k] = int(v)
                        continue
                except (TypeError, ValueError):
                    pass
                first_class[k] = v
            else:
                extra[k] = v
        return ExternalIds(**first_class, extra=extra)

    def index_pairs(self) -> List[Tuple[str, str]]:
        return list(self.identifiers.items())

    def __repr__(self) -> str:
        return f"MappingEntry(role={self.role.value!r}, name={self.name!r})"


# ---------------------------------------------------------------------------
# Mapping store
# ---------------------------------------------------------------------------

class MappingStore:
    """In-memory index of mapping entries."""

    def __init__(self) -> None:
        self._entries: List[MappingEntry] = []
        # (key, normalised_value) -> entry
        self._index: Dict[Tuple[str, str], MappingEntry] = {}

    def add(self, entry: MappingEntry) -> None:
        """Add an entry and index all its identifiers."""
        # Check for overlap with existing entries — if any identifier already
        # points to an entry of the same role, merge rather than duplicate.
        existing: Optional[MappingEntry] = None
        for k, v in entry.index_pairs():
            existing = self._index.get((k, v))
            if existing and existing.role == entry.role:
                break
        if existing and existing.role == entry.role:
            # Merge new identifiers into the existing entry.
            existing.identifiers.update(entry.identifiers)
            if entry.name and not existing.name:
                existing.name = entry.name
            # Re-index new keys — overwrite so merged entry wins for all keys.
            for k, v in entry.index_pairs():
                self._index[(k, v)] = existing
        else:
            self._entries.append(entry)
            for k, v in entry.index_pairs():
                self._index[(k, v)] = entry

    def lookup(self, role: EntityRole,
               ids: Dict[str, str]) -> Optional[MappingEntry]:
        """Return the first mapping entry that shares any identifier with
        ``ids`` and has the right ``role``.  ``ids`` values are raw strings
        (not yet normalised)."""
        for k, v in ids.items():
            entry = self._index.get((k, _norm(v)))
            if entry and entry.role == role:
                return entry
        return None

    def apply(self, role: EntityRole,
              external_ids: ExternalIds,
              min_score: float = 0.0) -> ExternalIds:
        """Enrich ``external_ids`` with any matching mapping entry.

        If no mapping matches, returns ``external_ids`` unchanged. Mappings
        whose ``score`` is below *min_score* are skipped — useful when
        callers ingest a mix of hand-curated (``score=1.0``) and
        auto-generated (probabilistic) entries.
        """
        # Build a flat dict of all identifiers to search against the index.
        probe: Dict[str, str] = {}
        for fname in _FIRST_CLASS:
            val = getattr(external_ids, fname, None)
            if val is not None:
                probe[fname] = str(val)
        probe.update(external_ids.extra)

        entry = self.lookup(role, probe)
        if entry is None or entry.score < min_score:
            return external_ids
        # Merge: mapping provides the base, actual result takes precedence.
        return entry.to_external_ids().merge(external_ids)

    def __len__(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# TOML parsing
# ---------------------------------------------------------------------------

_ROLE_MAP: Dict[str, EntityRole] = {
    k.value: k for k in EntityRole
}


def _parse_toml(data: dict) -> List[MappingEntry]:
    entries: List[MappingEntry] = []
    for kind_key, role in _ROLE_MAP.items():
        for raw in data.get(kind_key, []):
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            ids = {k: str(v) for k, v in raw.items() if k not in _SKIP_KEYS and v}
            if ids:
                entries.append(MappingEntry(role=role, name=name,
                                            identifiers=ids))
    return entries


def _load_file(path: Path) -> List[MappingEntry]:
    if not _TOML_AVAILABLE or not path.exists():
        return []
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        return _parse_toml(data)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Global store — lazily populated on first access
# ---------------------------------------------------------------------------

_STORE: Optional[MappingStore] = None
_STORE_LOCK = threading.Lock()


def _package_mappings_path() -> Optional[Path]:
    """Return the package mappings.toml path for the source-tree case.

    WARNING: for installed wheels the returned path is only valid inside an
    ``importlib.resources.as_file()`` context.  Prefer ``_load_package_entries``
    for production use.
    """
    try:
        ref = resources.files("metadatarr.data").joinpath("mappings.toml")
        with resources.as_file(ref) as p:
            # In the source tree, p is the real on-disk file and remains valid
            # after the context exits.  For installed wheels this may be a
            # temporary extraction; we return it here for test/inspection use.
            return Path(p)
    except Exception:
        return None


def _load_package_entries() -> List[MappingEntry]:
    """Load entries from the package-bundled mappings.toml inside its resource context."""
    try:
        ref = resources.files("metadatarr.data").joinpath("mappings.toml")
        with resources.as_file(ref) as p:
            return _load_file(Path(p))
    except Exception:
        return []


def _user_mappings_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "metadatarr" / "mappings.toml"


def _build_store() -> MappingStore:
    store = MappingStore()
    for e in _load_package_entries():
        store.add(e)
    for e in _load_file(_user_mappings_path()):
        store.add(e)
    return store


def get_store() -> MappingStore:
    """Return the global :class:`MappingStore`, building it on first call."""
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = _build_store()
    return _STORE


def reload() -> MappingStore:
    """Force a reload of both mapping files and return the new store."""
    global _STORE
    with _STORE_LOCK:
        _STORE = _build_store()
    return _STORE


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def apply_mappings(role: EntityRole, external_ids: ExternalIds) -> ExternalIds:
    """Enrich ``external_ids`` from the global mapping store.

    Shorthand for ``get_store().apply(role, external_ids)``.
    """
    return get_store().apply(role, external_ids)


def add_mapping(role: EntityRole, identifiers: Dict[str, str],
                name: Optional[str] = None,
                score: float = 1.0) -> MappingEntry:
    """Register a cross-platform identity assertion at runtime.

    ``identifiers`` is a ``{key: value}`` dict using the same key names as
    :class:`~mediavocab.models.ExternalIds` fields or any
    ``extra.*`` key a provider emits::

        add_mapping(
            EntityRole.ARTIST,
            {
                "soundcloud_artist_url": "https://soundcloud.com/acidkid",
                "bandcamp_artist_url": "https://piratech.bandcamp.com/",
            },
            name="Acidkid / Piratech",
        )

    The entry is merged into the global store immediately and persists for the
    lifetime of the process.  It is NOT written back to any TOML file.  Call
    :func:`reload` to discard runtime additions and revert to file state.
    """
    entry = MappingEntry(role=role, name=name, identifiers=identifiers,
                         score=score)
    get_store().add(entry)
    return entry
