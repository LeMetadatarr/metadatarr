# SPDX-License-Identifier: Apache-2.0
"""HTTP for the catalogue sources.

Every request goes through :func:`send`, which uses the package's shared
transport (per-host rate limits, the optional disk cache and the request's
cache bypass). Tests replace :func:`send` with a fixture router, so no source
reaches the network in the test suite.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from metadatarr.transport import make_session
from metadatarr.version import __version__

USER_AGENT = f"metadatarr/{__version__} (+https://github.com/LeMetadatarr/metadatarr)"

# Upper bound on a body read for one request (an RSS feed can be very large).
MAX_BODY_BYTES = 8 * 1024 * 1024

_SESSION = None

#: Seconds between two AniList requests: its limit is 30 a minute.
ANILIST_INTERVAL = 2.0


class UpstreamError(RuntimeError):
    """A catalogue answered with an error status or an unreadable body."""


class RateLimited(UpstreamError):
    """A catalogue answered 429. ``retry_after`` is its Retry-After in seconds, when it sent one."""

    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _session():
    global _SESSION
    if _SESSION is None:
        # AniList answers x-ratelimit-limit: 30 requests a minute.
        _SESSION = make_session({"graphql.anilist.co": ANILIST_INTERVAL})
    return _SESSION


def send(method: str, url: str, *, params: Optional[Dict[str, Any]] = None,
         json_body: Any = None, headers: Optional[Dict[str, str]] = None,
         timeout: float = 10.0, limit: int = MAX_BODY_BYTES) -> Tuple[int, bytes, Dict[str, str]]:
    """Perform one request and return ``(status, body, headers)``; the body is cut at ``limit`` bytes."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})
    with _session().request(method, url, params=params, json=json_body, headers=hdrs,
                            timeout=timeout, stream=True) as resp:
        body = bytearray()
        for chunk in resp.iter_content(65536):
            body.extend(chunk)
            if len(body) >= limit:
                break
        return resp.status_code, bytes(body[:limit]), dict(resp.headers)


def request(method: str, url: str, *, timeout: float, params: Optional[Dict[str, Any]] = None,
            json_body: Any = None, headers: Optional[Dict[str, str]] = None,
            limit: int = MAX_BODY_BYTES) -> Optional[bytes]:
    """The body of a successful answer, ``None`` for 404, :class:`UpstreamError` otherwise."""
    status, body, response_headers = send(method, url, params=params, json_body=json_body, headers=headers,
                                          timeout=timeout, limit=limit)
    if status == 404:
        return None
    if status == 429:
        retry = {k.lower(): v for k, v in (response_headers or {}).items()}.get("retry-after", "")
        try:
            seconds = float(retry)
        except ValueError:
            seconds = None
        raise RateLimited(f"{url} answered HTTP 429" + (f", retry after {retry} s" if seconds else ""), seconds)
    if status >= 400:
        raise UpstreamError(f"{url} answered HTTP {status}")
    return body


def get_json(url: str, *, timeout: float, params: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None) -> Any:
    body = request("GET", url, timeout=timeout, params=params, headers=headers)
    return _decode(url, body)


def post_json(url: str, payload: Any, *, timeout: float) -> Any:
    body = request("POST", url, timeout=timeout, json_body=payload)
    return _decode(url, body)


def _decode(url: str, body: Optional[bytes]) -> Any:
    if body is None:
        return None
    try:
        return json.loads(body)
    except ValueError as e:
        raise UpstreamError(f"{url} answered with a body that is not JSON") from e
