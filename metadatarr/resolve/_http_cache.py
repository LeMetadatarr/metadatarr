"""Deprecated compatibility shim for the HTTP disk cache.

Disk caching lives in :mod:`metadatarr.transport`, applied through the session
adapter mounted by :func:`metadatarr.transport.make_session`. Enabling it does
not require an explicit call — set ``METADATARR_HTTP_CACHE`` and the adapter
picks it up.

This module re-exports the cache maintenance helpers and keeps :func:`setup`
as a no-op so existing callers keep importing cleanly. It is removable in a
future major release.
"""
from __future__ import annotations

import logging
import os

from metadatarr.transport import clear, info

__all__ = ["setup", "clear", "info"]

LOG = logging.getLogger("metadatarr.resolve.http_cache")


def setup() -> bool:
    """No-op retained for backward compatibility.

    Disk caching activates from ``METADATARR_HTTP_CACHE`` via the transport
    adapter. Returns ``True`` when the environment enables caching.
    """
    LOG.warning(
        "metadatarr.resolve._http_cache.setup() is deprecated and does nothing; "
        "caching activates from METADATARR_HTTP_CACHE via metadatarr.transport"
    )
    return bool(os.environ.get("METADATARR_HTTP_CACHE", "").strip())
