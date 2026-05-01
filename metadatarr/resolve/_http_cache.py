"""Optional disk-backed HTTP cache for all provider requests.

Zero extra dependencies — uses stdlib only (hashlib, json, base64).
Monkey-patches ``requests.Session.send`` once on ``setup()``, so every
provider benefits without any code changes.

Environment variables
---------------------
``METADATARR_HTTP_CACHE``
    Set to ``1`` or any non-empty string to enable.  May also be set to an
    explicit cache directory path (e.g. ``/tmp/my_cache``); otherwise
    ``~/.cache/metadatarr/http`` is used.

``METADATARR_HTTP_CACHE_TTL``
    Cache TTL in seconds.  Defaults to ``86400`` (24 h).
    Set to ``0`` to cache indefinitely.

Usage
-----
No install needed — already included::

    METADATARR_HTTP_CACHE=1 python examples/resolve_movie.py

Or point at a custom directory::

    METADATARR_HTTP_CACHE=/tmp/my_cache python examples/resolve_movie.py

Clear the cache at the default location::

    python -c "import metadatarr.resolve._http_cache as c; c.clear()"

Inspect cache state::

    python -c "import metadatarr.resolve._http_cache as c; print(c.info())"
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

LOG = logging.getLogger("metadatarr.resolve.http_cache")

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "metadatarr" / "http"
_DEFAULT_TTL = 86400

_installed: bool = False
_cache_dir: Optional[Path] = None
_ttl: Optional[int] = None   # None = no expiry


# ---------------------------------------------------------------------------
# Internal helpers
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
        h.update(body)
    return h.hexdigest()


def _cache_path(key: str) -> Path:
    assert _cache_dir is not None
    return _cache_dir / f"{key}.json"


def _read_entry(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if _ttl:
        age = time.time() - data.get("ts", 0)
        if age > _ttl:
            try:
                path.unlink()
            except OSError:
                pass
            return None
    return data


def _write_entry(path: Path, response) -> None:
    try:
        content_b64 = base64.b64encode(response.content).decode("ascii")
        entry = {
            "ts": time.time(),
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "encoding": response.encoding,
            "url": response.url,
            "content_b64": content_b64,
        }
        path.write_text(json.dumps(entry, separators=(",", ":")), encoding="utf-8")
    except Exception as exc:
        LOG.debug("http_cache write failed: %s", exc)


def _make_response(entry: dict):
    """Reconstruct a minimal requests.Response from a cache entry."""
    import requests
    from requests.structures import CaseInsensitiveDict

    r = requests.Response()
    r.status_code = entry["status_code"]
    r.headers = CaseInsensitiveDict(entry.get("headers", {}))
    r.encoding = entry.get("encoding") or "utf-8"
    r.url = entry.get("url", "")
    r._content = base64.b64decode(entry["content_b64"])
    r._content_consumed = True
    return r


# ---------------------------------------------------------------------------
# Monkey-patch
# ---------------------------------------------------------------------------

def _patched_send(self, request, **kwargs):
    """Replacement for requests.Session.send that checks the disk cache."""
    # Only cache safe GET/HEAD requests.
    if request.method.upper() not in ("GET", "HEAD"):
        return _original_send(self, request, **kwargs)

    key = _cache_key(request.method, request.url, request.body)
    path = _cache_path(key)

    entry = _read_entry(path)
    if entry is not None:
        LOG.debug("http_cache HIT  %s", request.url)
        return _make_response(entry)

    LOG.debug("http_cache MISS %s", request.url)
    response = _original_send(self, request, **kwargs)
    if response.status_code == 200:
        _write_entry(path, response)
    return response


_original_send = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup() -> bool:
    """Activate disk caching if ``METADATARR_HTTP_CACHE`` is set.

    Safe to call multiple times — patches at most once per process.
    Returns ``True`` if caching is now active.
    """
    global _installed, _cache_dir, _ttl, _original_send

    if _installed:
        return True

    env = os.environ.get("METADATARR_HTTP_CACHE", "").strip()
    if not env:
        return False

    import requests

    _cache_dir = _resolve_dir(env)
    _cache_dir.mkdir(parents=True, exist_ok=True)

    ttl_raw = os.environ.get("METADATARR_HTTP_CACHE_TTL", str(_DEFAULT_TTL)).strip()
    try:
        ttl_val = int(ttl_raw)
        _ttl = ttl_val if ttl_val > 0 else None
    except ValueError:
        LOG.warning("Invalid METADATARR_HTTP_CACHE_TTL %r — using default", ttl_raw)
        _ttl = _DEFAULT_TTL

    _original_send = requests.Session.send
    requests.Session.send = _patched_send  # type: ignore[method-assign]

    _installed = True
    LOG.info(
        "HTTP cache enabled: path=%s ttl=%s",
        _cache_dir,
        f"{_ttl}s" if _ttl else "∞",
    )
    return True


def clear() -> int:
    """Delete all cached response files. Returns the number of files removed."""
    d = _cache_dir or _resolve_dir(os.environ.get("METADATARR_HTTP_CACHE", ""))
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
    d = _cache_dir or _resolve_dir(os.environ.get("METADATARR_HTTP_CACHE", "1"))
    files = list(d.glob("*.json")) if d.is_dir() else []
    return {
        "enabled": _installed,
        "path": str(d),
        "ttl": _ttl,
        "entries": len(files),
        "size_bytes": sum(f.stat().st_size for f in files),
    }
