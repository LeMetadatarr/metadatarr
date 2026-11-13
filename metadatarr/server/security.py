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
    of seconds until *cost* tokens are available. A cost above ``burst`` can
    never be met. Thread-safe.
    """

    _PRUNE_AT = 10_000

    def __init__(self, rate: float, burst: int,
                 time_func: Callable[[], float] = time.monotonic) -> None:
        self.rate = rate
        self.burst = burst
        self._time = time_func
        self._state: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str, cost: int = 1) -> float:
        now = self._time()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - last) * self.rate)
            if tokens >= cost:
                self._state[key] = (tokens - cost, now)
                wait = 0.0
            else:
                self._state[key] = (tokens, now)
                wait = (cost - tokens) / self.rate
            if len(self._state) > self._PRUNE_AT:
                self._prune(now)
        return wait

    def refund(self, key: str, cost: int = 1) -> None:
        """Give back *cost* tokens taken by :meth:`take` (never above ``burst``)."""
        with self._lock:
            if key in self._state:
                tokens, last = self._state[key]
                self._state[key] = (min(float(self.burst), tokens + cost), last)

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


_PROXY_HEADERS = (b"x-forwarded-for", b"forwarded", b"x-real-ip")


def _carries_forwarding_headers(request) -> bool:
    """True when the request names a client address in a proxy header.

    Behind uvicorn's default proxy-header handling the TCP peer is replaced by
    that header's value, so the address proves nothing whatever it looks like.
    """
    return any(name in _PROXY_HEADERS for name, _ in request.scope["headers"])


def _key_matches(candidate: str, keys: Sequence[str]) -> bool:
    found = False
    for key in keys:
        # Compare against every key so timing does not reveal which matched.
        found |= hmac.compare_digest(candidate.encode(), key.encode())
    return found


def install_access_control(app, config: ServerConfig,
                           time_func: Callable[[], float] = time.monotonic) -> None:
    """Add the API-key and rate-limit middleware to *app* when configured."""
    app.state.rate_bucket = None
    if not config.auth_enabled and config.rate_limit_per_minute <= 0:
        return

    from fastapi.responses import JSONResponse

    bucket = (TokenBucket(config.rate_limit_per_minute / 60.0, config.burst, time_func)
              if config.rate_limit_per_minute > 0 else None)

    app.state.rate_bucket = bucket

    @app.middleware("http")
    async def access_control(request, call_next):
        path = request.url.path
        if path in OPEN_PATHS or path.startswith(OPEN_PREFIXES):
            return await call_next(request)
        host = request.client.host if request.client else None
        if _carries_forwarding_headers(request):
            # A forwarded-address header may be forged and may already have
            # replaced the peer address: no exemption, one shared bucket.
            host = None
        if _in_networks(host, config.exempt_networks):
            return await call_next(request)

        key = request.headers.get("x-api-key") or request.query_params.get("apikey") or ""
        if config.auth_enabled and not (key and _key_matches(key, config.api_keys)):
            return JSONResponse({"detail": "missing or invalid API key"}, status_code=401,
                                headers={"WWW-Authenticate": "ApiKey"})

        if bucket is not None:
            ident = f"key:{key}" if config.auth_enabled else f"ip:{host or 'forwarded'}"
            request.state.rate_ident = ident
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


# Multipart framing around the file itself (boundaries, part headers).
UPLOAD_OVERHEAD_ALLOWANCE = 64 * 1024
UPLOAD_PATHS = ("/api/v1/identify/audio", "/identify/audio")


class _UploadTooLarge(Exception):
    pass


class UploadCapMiddleware:
    """Refuse an oversized upload before it is parsed or spooled.

    A ``Content-Length`` above *limit* is answered ``413`` at once; a body
    with no length (chunked) is counted as it is received and aborted with
    ``413`` once it passes *limit*. Only :data:`UPLOAD_PATHS` are covered.
    """

    def __init__(self, app, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send) -> None:
        path = scope["path"]
        root = scope.get("root_path", "")
        if root and path.startswith(root + "/"):
            path = path[len(root):]
        if (scope["type"] != "http" or scope["method"] != "POST"
                or path not in UPLOAD_PATHS):
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.limit
            except ValueError:
                too_big = False
            if too_big:
                await self._refuse(send)
                return

        received = 0
        exceeded = False
        started = False

        async def counting_receive():
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    exceeded = True
                    raise _UploadTooLarge
            return message

        async def guarded_send(message):
            nonlocal started
            if exceeded:
                return  # whatever the app made of the aborted read is dropped
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _UploadTooLarge:
            pass
        if exceeded and not started:
            await self._refuse(send)

    @staticmethod
    async def _refuse(send) -> None:
        body = b'{"detail":"upload too large"}'
        await send({"type": "http.response.start", "status": 413, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"connection", b"close"),
        ]})
        await send({"type": "http.response.body", "body": body})
