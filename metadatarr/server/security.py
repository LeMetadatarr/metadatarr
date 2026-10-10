# SPDX-License-Identifier: Apache-2.0
"""Access control for the HTTP server: API keys, rate limiting, and the
allow-list that confines ``/identify/audio?path=`` to configured roots."""
from __future__ import annotations

import hmac
import ipaddress
import math
import os
import threading
import time
from typing import Callable, Dict, Optional, Sequence, Tuple

from metadatarr.server.config import IPNetwork, ServerConfig

# Paths served without a key and without rate limiting: liveness probes and
# the WebUI's static assets.
OPEN_PATHS = ("/healthz", "/api/v1/healthz")
OPEN_PREFIXES = ("/static/",)


class TokenBucket:
    """Per-key token buckets: ``burst`` tokens, refilled at ``rate`` per second.

    :meth:`take` returns ``0.0`` when a token was spent, otherwise the number
    of seconds until one is available. Thread-safe.
    """

    _PRUNE_AT = 10_000

    def __init__(self, rate: float, burst: int,
                 time_func: Callable[[], float] = time.monotonic) -> None:
        self.rate = rate
        self.burst = burst
        self._time = time_func
        self._state: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str) -> float:
        now = self._time()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - last) * self.rate)
            if tokens >= 1.0:
                self._state[key] = (tokens - 1.0, now)
                wait = 0.0
            else:
                self._state[key] = (tokens, now)
                wait = (1.0 - tokens) / self.rate
            if len(self._state) > self._PRUNE_AT:
                self._prune(now)
        return wait

    def _prune(self, now: float) -> None:
        # A bucket idle long enough to have refilled is indistinguishable
        # from a fresh one, so dropping it loses nothing.
        full_after = self.burst / self.rate
        for k in [k for k, (_, last) in self._state.items() if now - last >= full_after]:
            del self._state[k]


def _in_networks(host: Optional[str], networks: Sequence[IPNetwork]) -> bool:
    if not host or not networks:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return any(addr in net for net in networks)


def _key_matches(candidate: str, keys: Sequence[str]) -> bool:
    found = False
    for key in keys:
        # Compare against every key so timing does not reveal which matched.
        found |= hmac.compare_digest(candidate.encode(), key.encode())
    return found


def install_access_control(app, config: ServerConfig,
                           time_func: Callable[[], float] = time.monotonic) -> None:
    """Add the API-key and rate-limit middleware to *app* when configured."""
    if not config.auth_enabled and config.rate_limit_per_minute <= 0:
        return

    from fastapi.responses import JSONResponse

    bucket = (TokenBucket(config.rate_limit_per_minute / 60.0, config.burst, time_func)
              if config.rate_limit_per_minute > 0 else None)

    @app.middleware("http")
    async def access_control(request, call_next):
        path = request.url.path
        if path in OPEN_PATHS or path.startswith(OPEN_PREFIXES):
            return await call_next(request)
        host = request.client.host if request.client else None
        if _in_networks(host, config.exempt_networks):
            return await call_next(request)

        key = request.headers.get("x-api-key") or request.query_params.get("apikey") or ""
        if config.auth_enabled and not (key and _key_matches(key, config.api_keys)):
            return JSONResponse({"detail": "missing or invalid API key"}, status_code=401,
                                headers={"WWW-Authenticate": "ApiKey"})

        if bucket is not None:
            ident = f"key:{key}" if config.auth_enabled else f"ip:{host}"
            wait = bucket.take(ident)
            if wait > 0:
                return JSONResponse({"detail": "rate limit exceeded"}, status_code=429,
                                    headers={"Retry-After": str(max(1, math.ceil(wait)))})
        return await call_next(request)


class PathNotAllowed(Exception):
    """A requested path lies outside every configured root."""


def resolve_allowed_path(path: str, roots: Sequence[str]) -> str:
    """Return the real path of *path* when it is a regular file under one of
    *roots* (after resolving symlinks and ``..``), else raise
    :class:`PathNotAllowed`."""
    if not roots:
        raise PathNotAllowed("path lookups are disabled; upload the file instead")
    if "\x00" in path:
        raise PathNotAllowed("path is not under an allowed root")
    real = os.path.realpath(path)
    for root in roots:
        real_root = os.path.realpath(root)
        try:
            inside = os.path.commonpath([real_root, real]) == real_root
        except ValueError:  # different drives on Windows
            inside = False
        if inside:
            if not os.path.isfile(real):
                raise PathNotAllowed("path is not a file under an allowed root")
            return real
    raise PathNotAllowed("path is not under an allowed root")
