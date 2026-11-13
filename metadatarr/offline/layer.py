# SPDX-License-Identifier: Apache-2.0
"""How the resolver and the catalogue use the offline sets.

The functions below are called from the existing code paths. Each returns
``None`` (or nothing) when the layer is off, the set is not built, the row is
missing or older than the configured maximum age, or the request asks for a
refresh; the caller then asks its live provider exactly as before.

- :func:`front_candidates` answers a title search for a provider a set fronts.
- :func:`front_enrich` answers an id enrichment for a provider a set fronts.
- :func:`front_lookup` answers a catalogue lookup by external id.
- :func:`extra_candidates` and :func:`extra_enrich` add what the stand-alone
  sets know; no live provider competes for those, so they are served at any age.

External ids are checked with the same rules the routes use
(:func:`metadatarr.catalog.base.check_external_ids`) before they reach SQL.
"""
from __future__ import annotations

import contextlib
import contextvars
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals, match_quality

from metadatarr.catalog.base import InvalidId, check_external_ids
from metadatarr.catalog.ids import from_native, native_field, to_native
from metadatarr.catalog.shapes import Item, iso_date
from metadatarr.catalog.sources._util import plain_text
from metadatarr.offline.config import OfflineConfig
from metadatarr.offline.sets import SETS, SetSpec
from metadatarr.offline.store import Row, SetInfo, Store
from metadatarr.transport import cache_bypassed

#: Provider name on matches that come from a stand-alone set.
PROVIDER = "ledata"
LIVE: Dict[str, Any] = {"source": "live"}
#: Confidence ceiling of an offline match, the same ceiling the live title searches use.
CONFIDENCE = 0.7
#: Most candidates one set contributes to a title search.
CANDIDATE_LIMIT = 5

_FRONTS: Dict[str, List[SetSpec]] = {}
_LOOKUPS: Dict[Tuple[str, str], List[SetSpec]] = {}
_STANDALONE: List[SetSpec] = [s for s in SETS if not s.front]
for _spec in SETS:
    if _spec.front:
        _FRONTS.setdefault(_spec.front, []).append(_spec)
    for _key in _spec.lookups:
        _LOOKUPS.setdefault(_key, []).append(_spec)

_state_lock = threading.Lock()
_state: Optional[Tuple[OfflineConfig, Optional[Store]]] = None
_clock = time.time
_served: contextvars.ContextVar = contextvars.ContextVar("metadatarr_offline_served", default=None)


def configure(config: Optional[OfflineConfig] = None, clock=time.time) -> None:
    """Use ``config`` instead of the environment; ``None`` reads the environment again."""
    global _state, _clock
    with _state_lock:
        _clock = clock
        _state = None if config is None else (config, Store(config.data_dir) if config.enabled else None)


def _layer() -> Optional[Tuple[OfflineConfig, Store]]:
    global _state
    with _state_lock:
        if _state is None:
            config = OfflineConfig.from_env()
            _state = (config, Store(config.data_dir) if config.enabled else None)
        config, store = _state
    return (config, store) if store is not None else None


def enabled() -> bool:
    return _layer() is not None


@contextlib.contextmanager
def collect_origins() -> Iterator[List[Dict[str, Any]]]:
    """The origins of the offline answers given inside the block, for routes whose
    response has no field to carry them."""
    seen: List[Dict[str, Any]] = []
    token = _served.set(seen)
    try:
        yield seen
    finally:
        _served.reset(token)


def _note(origin: Dict[str, Any]) -> None:
    seen = _served.get()
    if seen is not None and origin not in seen:
        seen.append(origin)


def stamp_live(matches: List[Any]) -> List[Any]:
    """Mark matches a live provider gave, when the layer is on."""
    if enabled():
        for m in matches:
            if m.origin is None:
                m.origin = LIVE
    return matches


def _fresh(config: OfflineConfig, store: Store, spec: SetSpec) -> Optional[SetInfo]:
    info = store.info(spec.name)
    if info is None or info.stale(config.max_age, _clock()):
        return None
    return info


def to_external_ids(ids: Dict[str, str]) -> ExternalIds:
    """ExternalIds from ``{field: value}``; ids the model has no field for go to ``extra``."""
    fields: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    for name, value in ids.items():
        field = ExternalIds.model_fields.get(name)
        if field is None or name == "extra":
            extra[name] = value
            continue
        annotation = str(field.annotation)
        if "int" in annotation and "str" not in annotation:
            if value.isascii() and value.isdigit():
                fields[name] = int(value)
            else:
                extra[name] = value
        else:
            fields[name] = value
    try:
        return ExternalIds(**fields, extra=extra)
    except ValueError:
        return ExternalIds(extra=extra)


def _ids_asked(spec: SetSpec, external_ids: ExternalIds) -> Dict[str, str]:
    """The ids of ``external_ids`` this set is keyed by, as ``{field: text}``."""
    asked: Dict[str, str] = {}
    for field in dict.fromkeys(spec.ids.values()):
        value = (external_ids.extra or {}).get(field) if field not in ExternalIds.model_fields \
            else getattr(external_ids, field, None)
        if value not in (None, ""):
            text = str(value).strip()
            asked[field] = text.replace("-", "").upper() if field in ("isbn_10", "isbn_13") else text
    return asked


def _valid(external_ids: ExternalIds) -> bool:
    try:
        check_external_ids(external_ids)
    except InvalidId:
        return False
    return True


def _medium(spec: SetSpec, row: Row, signals: Signals) -> MediaType:
    asked = getattr(signals.medium, "value", signals.medium)
    if row.kind == "movie" and "movie" in spec.media:
        return MediaType.MOVIE
    return MediaType(asked if asked in spec.media else spec.media[0])


def _match(spec: SetSpec, row: Row, signals: Signals, info: SetInfo, provider: str):
    from metadatarr.resolve.base import ProviderMatch

    candidate = Signals(title=row.title, artist=row.data.get("artist"), year=row.year,
                        medium=_medium(spec, row, signals))
    return ProviderMatch(provider=provider, confidence=CONFIDENCE * match_quality(signals, candidate),
                         signals=candidate, external_ids=to_external_ids(row.ids), origin=info.origin())


def front_candidates(provider: str, signals: Signals) -> Optional[List[Any]]:
    """The offline matches for ``provider``'s title search, or ``None`` to ask the provider."""
    layer = _layer()
    specs = _FRONTS.get(provider)
    if layer is None or not specs or cache_bypassed() or not signals.title or signals.medium is None:
        return None
    config, store = layer
    asked = getattr(signals.medium, "value", signals.medium)
    for spec in specs:
        info = _fresh(config, store, spec) if asked in spec.media else None
        rows = store.find_name(spec.name, signals.title, CANDIDATE_LIMIT) if info else []
        if rows:
            _note(info.origin())
            return [_match(spec, row, signals, info, provider) for row in rows]
    return None


def front_enrich(provider: Any, external_ids: ExternalIds) -> Optional[ExternalIds]:
    """The offline enrichment for ``provider``, or ``None`` to ask the provider."""
    from metadatarr.resolve.base import MetadataProvider

    layer = _layer()
    specs = _FRONTS.get(provider.name)
    if (layer is None or not specs or cache_bypassed() or not _valid(external_ids)
            or type(provider).enrich is MetadataProvider.enrich):
        return None
    config, store = layer
    for spec in specs:
        asked = _ids_asked(spec, external_ids)
        info = _fresh(config, store, spec) if asked else None
        row = store.find_ids(spec.name, asked) if info else None
        if row is not None:
            _note(info.origin())
            return to_external_ids(row.ids)
    return None


def _item(row: Row) -> Item:
    d = row.data
    ids = to_external_ids(row.ids)
    return Item(kind=row.kind, title=row.title, sort_title=d.get("sort_title", ""),
                original_title=d.get("original_title", ""), year=row.year,
                release_date=iso_date(d.get("release_date")), runtime_min=d.get("runtime_min"),
                overview=plain_text(d.get("overview")), poster_url=d.get("poster_url", ""),
                ext_ids=from_native(ids, row.kind), extra={**ids.extra, **(d.get("extra") or {})})


def front_lookup(scheme: str, value: str, kind: Optional[str], children: bool,
                 refresh: bool) -> Optional[Tuple[Item, Dict[str, Any]]]:
    """``(item, origin)`` for a catalogue lookup the offline sets can answer, else ``None``."""
    layer = _layer()
    specs = _LOOKUPS.get((scheme, kind or ""))
    if layer is None or not specs or refresh or cache_bypassed():
        return None
    config, store = layer
    native = to_native({scheme: value}, kind)
    field = native_field(scheme, kind, value)
    if not field or not _valid(native):
        return None
    asked = value.replace("-", "").upper() if field in ("isbn_10", "isbn_13") else str(
        getattr(native, field, None) or value)
    for spec in specs:
        if children and spec.children:
            continue
        info = _fresh(config, store, spec)
        row = store.find_ids(spec.name, {field: asked}) if info else None
        if row is not None:
            return _item(row), info.origin()
    return None


def _search_text(spec: SetSpec, signals: Signals) -> str:
    if spec.kind == "artist":
        return (signals.artist or "") if not signals.title else ""
    return signals.title or ""


def extra_candidates(signals: Signals) -> List[Any]:
    """Matches from the stand-alone sets for ``signals``; empty when the layer is off."""
    layer = _layer()
    asked = getattr(signals.medium, "value", signals.medium)
    if layer is None or asked is None:
        return []
    _, store = layer
    out: List[Any] = []
    seen = set()
    for spec in _STANDALONE:
        text = _search_text(spec, signals) if asked in spec.media else ""
        info = store.info(spec.name) if text else None
        for row in (store.find_name(spec.name, text, CANDIDATE_LIMIT) if info else []):
            key = (row.kind, next(iter(row.ids.items()), None) or row.title)
            if key in seen:
                continue
            seen.add(key)
            _note(info.origin())
            out.append(_match(spec, row, signals, info, PROVIDER))
    return out


def extra_enrich(external_ids: ExternalIds) -> Optional[ExternalIds]:
    """The ids the stand-alone sets hold for the ones given, or ``None``."""
    layer = _layer()
    if layer is None or not _valid(external_ids):
        return None
    _, store = layer
    found: Optional[ExternalIds] = None
    for spec in _STANDALONE:
        asked = _ids_asked(spec, external_ids)
        info = store.info(spec.name) if asked else None
        row = store.find_ids(spec.name, asked) if info else None
        if row is not None:
            _note(info.origin())
            ids = to_external_ids(row.ids)
            found = ids if found is None else found.merge(ids)
    return found
