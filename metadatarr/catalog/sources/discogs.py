# SPDX-License-Identifier: Apache-2.0
"""Discogs: the videos listed on a release, as the album's extras. No key is
needed; with ``DISCOGS_TOKEN`` set the requests carry it, as the resolver's
Discogs client does, and share that client's pacing (25 requests a minute
without a token, 60 with one).

Discogs gives a release's videos no type; they are the videos collectors link
to the record (mostly its tracks on YouTube), so each is a ``music-video``
whose ``type_raw`` is ``video``, and ``official`` stays unknown."""
from __future__ import annotations

import os

from metadatarr.catalog import _http
from metadatarr.catalog.base import CatalogSource, register_source
from metadatarr.catalog.shapes import Extra
from metadatarr.catalog.sources._util import plain_text, video_site_key

API = "https://api.discogs.com"


def _extra(v: dict) -> Extra:
    url = (v.get("uri") or "").strip()
    site, key = video_site_key(url)
    duration = v.get("duration")
    return Extra(type="music-video", type_raw="video", title=plain_text(v.get("title"), 300), site=site, key=key,
                 url=url, runtime_s=float(duration) if isinstance(duration, (int, float)) and duration > 0 else None)


class DiscogsSource(CatalogSource):
    name = "discogs"
    priority = 60
    extras_kinds = {"album": ("discogs",)}

    def extras(self, scheme, value, kind, *, timeout):
        if not (value.isascii() and value.isdigit()):
            return None
        token = os.environ.get("DISCOGS_TOKEN", "").strip()
        headers = {"Authorization": f"Discogs token={token}"} if token else None
        release = _http.get_json(f"{API}/releases/{value}", timeout=timeout, headers=headers)
        if not isinstance(release, dict) or not release.get("id"):
            return None
        return [_extra(v) for v in release.get("videos") or []
                if isinstance(v, dict) and str(v.get("uri") or "").startswith(("http://", "https://"))]


register_source(DiscogsSource())
