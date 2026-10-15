# SPDX-License-Identifier: Apache-2.0
"""The Internet Fanedit Database (fanedit.org), keyless: the fan edits of a
movie or a series, as variants.

IFDB is searched by the work's title, so a question names the work by its id
and its title. Each edit is an item of the work's kind whose ``extra.variant``
holds the edit's name, its faneditor, its release date, its page and IFDB's
type, and whose ``ext_ids.ifdb`` is its IFDB id when the search result gives
one. A search that fails is an error of the answer, never an empty list."""
from __future__ import annotations

import re
from typing import Optional

from metadatarr.catalog.base import CatalogSource, register_source
from metadatarr.catalog.shapes import Item, iso_date, year_of
from metadatarr.catalog.sources._util import ids, plain_text
from metadatarr.resolve.providers.pyfanedit import variant_extra

_CLOCK = re.compile(r"^(?:(\d+):)?(\d+):\d{2}$")
_HOURS = re.compile(r"(\d+(?:\.\d+)?)\s*h(?:ours?|rs?)?\b")
_MINUTES = re.compile(r"(\d+)\s*m(?:in(?:ute)?s?)?\b")


def runtime_minutes(text: Optional[str]) -> Optional[float]:
    """Minutes from IFDB's running time ("1h 45m", "105 min", "105", "1:45:00"), or None."""
    t = (text or "").strip().lower()
    clock = _CLOCK.match(t)
    if clock:
        total = int(clock.group(1) or 0) * 60 + int(clock.group(2)) if clock.group(1) else int(clock.group(2))
    elif t.replace(".", "", 1).isdigit():
        total = float(t)
    else:
        hours, minutes = _HOURS.search(t), _MINUTES.search(t)
        total = (float(hours.group(1)) * 60 if hours else 0) + (int(minutes.group(1)) if minutes else 0)
    return round(float(total), 2) if total else None


class PyfaneditSource(CatalogSource):
    name = "pyfanedit"
    priority = 50
    variants_kinds = {"movie": ("tmdb", "imdb"), "series": ("tvdb", "tmdb", "imdb")}

    def variants(self, scheme, value, kind, *, title, year, timeout):
        from metadatarr.resolve.base import all_providers

        provider = all_providers()["pyfanedit"]
        out = []
        for summary in provider.search(title):
            extra = variant_extra(summary)
            released = extra.get("fanedit_release_date") or ""
            variant = {
                "type": "fanedit", "name": extra.get("edit_name") or "", "editor": extra.get("faneditor") or "",
                "version": "", "source_formats": [], "released": released, "url": extra.get("fanedit_url") or "",
                "subtype": extra.get("fanedit_subtype") or (summary.fanedit_type or "").lower(),
                "of": {scheme: value},
                **{k: extra[k] for k in ("running_time", "available_in", "release_information") if k in extra},
            }
            out.append(Item(
                kind=kind, title=summary.title, year=year_of(iso_date(released)), release_date=iso_date(released),
                runtime_min=runtime_minutes(extra.get("running_time")), overview=plain_text(extra.get("synopsis")),
                poster_url=extra.get("cover_url") or "", ext_ids=ids(ifdb=summary.fanedit_id),
                extra={"variant": variant},
            ))
        return out


register_source(PyfaneditSource())
