"""Shared HTTP transport for every first-party request in the package.

A single :func:`make_session` builds a :class:`requests.Session` whose adapter
provides two things every provider and client benefits from:

- **Per-host rate limiting** — a process-wide :class:`HostRateLimiter` spaces
  requests to throttled hosts (see :data:`BUILTIN_RATE_LIMITS`), so the
  concurrent fan-out cannot burst a single host through several providers that
  share it.
- **Opt-in disk caching** — GET/HEAD responses with status ``200`` are stored
  on disk when ``METADATARR_HTTP_CACHE`` is set, using stdlib only (hashlib,
  json, base64).

Scope: this applies to HTTP issued directly by this package. Providers whose
network access happens inside sibling libraries reach the network through those
libraries' own sessions and are not covered here.

Environment variables
---------------------
``METADATARR_HTTP_CACHE``
    Set to ``1`` or any non-empty string to enable disk caching.  May also be
    set to an explicit cache directory path (e.g. ``/tmp/my_cache``); otherwise
    ``~/.cache/metadatarr/http`` is used.

``METADATARR_HTTP_CACHE_TTL``
    Cache TTL in seconds.  Defaults to ``86400`` (24 h).
    Set to ``0`` to cache indefinitely.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional
from urllib.parse import urlsplit

import requests
import requests.adapters

LOG = logging.getLogger("metadatarr.transport")

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "metadatarr" / "http"
_DEFAULT_TTL = 86400

# Minimum seconds between requests per host, from each service's published
# policy.  Unlisted hosts are not throttled (default interval 0.0).
BUILTIN_RATE_LIMITS: Dict[str, float] = {
    "musicbrainz.org": 1.0,   # https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting — 1 req/s
    "api.discogs.com": 1.0,   # https://www.discogs.com/developers — 60 req/min authenticated
    "www.wikidata.org": 0.5,  # https://www.wikidata.org/wiki/Wikidata:Data_access — courteous 2 req/s
}


# ---------------------------------------------------------------------------
# Per-host rate limiter
# ---------------------------------------------------------------------------

class HostRateLimiter:
    """Per-host minimum-interval limiter (thread-safe).

    Blocks the calling thread until the host's interval has elapsed. The next
    permitted moment is reserved under the lock and the sleep happens outside
    it, so concurrent callers to the same host queue rather than collide.
    """

    def __init__(self, default_interval: float = 0.0,
                 per_host: Optional[Dict[str, float]] = None,
                 time_func: Callable[[], float] = time.monotonic,
                 sleep_func: Callable[[float], None] = time.sleep) -> None:
        self._default = default_interval
        self._per_host: Dict[str, float] = dict(per_host or {})
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._time = time_func
        self._sleep = sleep_func

    def set_interval(self, host: str, interval: float) -> None:
        with self._lock:
            self._per_host[host.lower()] = interval

    def wait(self, host: str) -> None:
        host = host.lower()
        with self._lock:
            interval = self._per_host.get(host, self._default)
            if interval <= 0:
                return
            now = self._time()
            last = self._last.get(host)
            earliest = now if last is None else last + interval
            if earliest <= now:
                self._last[host] = now
                return
            # Reserve this host's slot before releasing the lock so a peer
            # thread queues behind us instead of racing to the same instant.
            self._last[host] = earliest
            sleep_for = earliest - now
        self._sleep(sleep_for)


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------

def _resolve_dir(env_value: str) -> Path:
    v = env_value.strip()
    if v and v not in ("1", "true", "yes", "on"):
        return Path(v).expanduser()
    return _DEFAULT_CACHE_DIR


def _cache_key(method: str, url: str, body: Optional[bytes]) -> str:
    h = hashlib.sha1()
    h.update(method.upper().encode())
    h.update(url.encode())
    if body:
        h.update(body if isinstance(body, bytes) else str(body).encode())
    return h.hexdigest()


def _make_response(entry: dict) -> requests.Response:
    """Reconstruct a minimal :class:`requests.Response` from a cache entry."""
    from requests.structures import CaseInsensitiveDict

    r = requests.Response()
    r.status_code = entry["status_code"]
    r.headers = CaseInsensitiveDict(entry.get("headers", {}))
    r.encoding = entry.get("encoding") or "utf-8"
    r.url = entry.get("url", "")
    r._content = base64.b64decode(entry["content_b64"])
    r._content_consumed = True
    return r


class DiskCache:
    """On-disk store for GET/HEAD responses, keyed by method+url+body."""

    def __init__(self, directory: Path, ttl: Optional[int]) -> None:
        self.directory = directory
        self.ttl = ttl  # None = no expiry
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, method: str, url: str, body: Optional[bytes]) -> Optional[requests.Response]:
        path = self._path(_cache_key(method, url, body))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if self.ttl:
            age = time.time() - data.get("ts", 0)
            if age > self.ttl:
                try:
                    path.unlink()
                except OSError:
                    pass
                return None
        LOG.debug("http_cache HIT  %s", url)
        return _make_response(data)

    def store(self, method: str, url: str, body: Optional[bytes],
              response: requests.Response) -> None:
        path = self._path(_cache_key(method, url, body))
        try:
            entry = {
                "ts": time.time(),
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "encoding": response.encoding,
                "url": response.url,
                "content_b64": base64.b64encode(response.content).decode("ascii"),
            }
            path.write_text(json.dumps(entry, separators=(",", ":")), encoding="utf-8")
        except Exception as exc:
            LOG.debug("http_cache write failed: %s", exc)


def _cache_from_env() -> Optional[DiskCache]:
    """Build a :class:`DiskCache` from the environment, or ``None`` if off."""
    env = os.environ.get("METADATARR_HTTP_CACHE", "").strip()
    if not env:
        return None
    ttl_raw = os.environ.get("METADATARR_HTTP_CACHE_TTL", str(_DEFAULT_TTL)).strip()
    try:
        ttl_val = int(ttl_raw)
        ttl: Optional[int] = ttl_val if ttl_val > 0 else None
    except ValueError:
        LOG.warning("Invalid METADATARR_HTTP_CACHE_TTL %r — using default", ttl_raw)
        ttl = _DEFAULT_TTL
    cache = DiskCache(_resolve_dir(env), ttl)
    LOG.info("HTTP cache enabled: path=%s ttl=%s",
             cache.directory, f"{ttl}s" if ttl else "∞")
    return cache


# ---------------------------------------------------------------------------
# Adapter + session factory
# ---------------------------------------------------------------------------

# Shared across every session so per-host spacing is coordinated process-wide.
_GLOBAL_LIMITER = HostRateLimiter(per_host=BUILTIN_RATE_LIMITS)


class CachingRateLimitedAdapter(requests.adapters.HTTPAdapter):
    """HTTPAdapter that applies :meth:`HostRateLimiter.wait` before each send
    and serves/writes the disk cache for GET/HEAD ``200`` responses."""

    def __init__(self, limiter: HostRateLimiter,
                 cache: Optional[DiskCache] = None, **kwargs) -> None:
        self._limiter = limiter
        self._cache = cache
        super().__init__(**kwargs)

    def send(self, request, **kwargs):  # type: ignore[override]
        host = urlsplit(request.url).netloc.lower()
        self._limiter.wait(host)

        cacheable = self._cache is not None and request.method.upper() in ("GET", "HEAD")
        if not cacheable:
            return super().send(request, **kwargs)

        hit = self._cache.get(request.method, request.url, request.body)
        if hit is not None:
            return hit
        LOG.debug("http_cache MISS %s", request.url)
        response = super().send(request, **kwargs)
        if response.status_code == 200:
            self._cache.store(request.method, request.url, request.body, response)
        return response


def make_session(rate_limits: Optional[Dict[str, float]] = None) -> requests.Session:
    """Build a :class:`requests.Session` mounting :class:`CachingRateLimitedAdapter`
    on ``http://`` and ``https://``.

    *rate_limits* registers or overrides per-host minimum intervals (seconds) on
    the shared limiter, so a caller with a stricter policy (e.g. a token-scoped
    limit) can tighten a host without weakening it for others.
    """
    if rate_limits:
        for host, interval in rate_limits.items():
            _GLOBAL_LIMITER.set_interval(host, interval)

    adapter = CachingRateLimitedAdapter(_GLOBAL_LIMITER, _cache_from_env())
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# ---------------------------------------------------------------------------
# Cache maintenance utilities
# ---------------------------------------------------------------------------

def clear() -> int:
    """Delete all cached response files. Returns the number of files removed."""
    d = _resolve_dir(os.environ.get("METADATARR_HTTP_CACHE", ""))
    if not d.is_dir():
        return 0
    count = 0
    for p in d.glob("*.json"):
        try:
            p.unlink()
            count += 1
        except OSError:
            pass
    LOG.info("HTTP cache cleared: %d file(s) removed from %s", count, d)
    return count


def info() -> dict:
    """Return a dict describing the current cache state."""
    env = os.environ.get("METADATARR_HTTP_CACHE", "").strip()
    d = _resolve_dir(env or "1")
    files = list(d.glob("*.json")) if d.is_dir() else []
    ttl_raw = os.environ.get("METADATARR_HTTP_CACHE_TTL", str(_DEFAULT_TTL)).strip()
    try:
        ttl_val = int(ttl_raw)
        ttl: Optional[int] = ttl_val if ttl_val > 0 else None
    except ValueError:
        ttl = _DEFAULT_TTL
    return {
        "enabled": bool(env),
        "path": str(d),
        "ttl": ttl,
        "entries": len(files),
        "size_bytes": sum(f.stat().st_size for f in files),
    }
