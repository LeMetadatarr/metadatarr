"""Provider lookup cache.

Wraps :meth:`MetadataProvider.lookup` calls in a process-wide LRU cache
keyed by ``(provider_name, signal_hash)``. Hits *and* misses are cached:
a sentinel ``None`` records "this provider has nothing for this input"
so we don't re-query the network for inputs we've already failed on.

The cache is opt-in. :func:`metadatarr.resolve.base.resolve` consults
it via :func:`cached_lookup`; direct ``provider.lookup()`` calls remain
uncached so unit tests stay deterministic.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import TYPE_CHECKING, Optional, Tuple

import hashlib

from mediavocab.models.signals import Signals, signal_hash

if TYPE_CHECKING:
    from metadatarr.resolve.base import MetadataProvider, ProviderMatch
    from mediavocab.models import ExternalIds


# A small sentinel that indicates "we asked, and the provider returned None".
_MISS = object()

_DEFAULT_MAX = 1024


class _LRU:
    """Tiny thread-safe LRU. Avoids functools.lru_cache because we want
    to expose ``clear`` and ``set_max`` to consumers and the keys aren't
    hashable in a way functools likes (Signals isn't hashable on its own,
    and we don't want callers to need to hash it themselves)."""

    def __init__(self, max_entries: int = _DEFAULT_MAX) -> None:
        self._max = max_entries
        self._data: "OrderedDict[Tuple[str, str], object]" = OrderedDict()
        self._lock = Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Tuple[str, str]):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def put(self, key: Tuple[str, str], value) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0

    def __contains__(self, key) -> bool:
        with self._lock:
            return key in self._data

    def __len__(self) -> int:
        return len(self._data)


_CACHE = _LRU()


def cache() -> _LRU:
    """Return the global provider-lookup cache (for inspection / clear)."""
    return _CACHE


def cached_lookup(provider: "MetadataProvider",
                  signals: Signals) -> Optional["ProviderMatch"]:
    """Look up *signals* via *provider*, memoising both hits and misses."""
    key = (provider.name, signal_hash(signals))
    hit = _CACHE.get(key)
    if hit is _MISS:
        return None
    if hit is not None:
        return hit  # cached ProviderMatch
    try:
        result = provider.lookup(signals)
    except Exception:
        # Do not cache transient failures — allow retry on next call.
        return None
    _CACHE.put(key, result if result is not None else _MISS)
    return result


def _external_ids_hash(external_ids: "ExternalIds") -> str:
    """Stable hash of an ExternalIds payload, suitable as a cache key."""
    payload = external_ids.model_dump_json(exclude_none=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def cached_enrich(provider: "MetadataProvider",
                  external_ids: "ExternalIds") -> Optional["ExternalIds"]:
    """Run *provider*.enrich over *external_ids*, memoising both hits and
    misses. Uses the same LRU instance as :func:`cached_lookup` but a
    distinct ``"enrich:"``-prefixed key namespace so the two domains never
    collide."""
    key = ("enrich:" + provider.name, _external_ids_hash(external_ids))
    hit = _CACHE.get(key)
    if hit is _MISS:
        return None
    if hit is not None:
        return hit  # cached ExternalIds
    try:
        result = provider.enrich(external_ids)
    except Exception:
        # Do not cache transient failures — allow retry on next call.
        return None
    _CACHE.put(key, result if result is not None else _MISS)
    return result
