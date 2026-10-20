# SPDX-License-Identifier: Apache-2.0
"""The Internet Fanedit Database (fanedit.org), keyless: the fan edits of a
movie or a series, as variants.

IFDB is searched by the work's title, so a question names the work by its id
and its title. Each edit is an item of the work's kind whose ``extra.variant``
holds the edit's name, its faneditor, its release date, its page and IFDB's
type, and whose ``ext_ids.ifdb`` is its IFDB id when the search result gives
one. When the work's ``year`` is known, the edits released more than a year
before it are dropped, since IFDB's search by title cannot tell a film from its
remake; an edit with no release date is kept. A search that fails is an error of
the answer, never an empty list."""
from __future__ import annotations

import re
from typing import Optional

from metadatarr.catalog.base import CatalogSource, register_source
from metadatarr.catalog.shapes import Item, year_of
from metadatarr.catalog.sources._util import ids, plain_text
from metadatarr.resolve.providers.pyfanedit import variant_extra

_NUMBER = r"[0-9]{1,3}(?:[.,][0-9]{1,3})?"
_CLOCK = re.compile(r"^([0-9]{1,3}):([0-5][0-9])(?::[0-5][0-9])?$")
_PLAIN = re.compile(r"^[0-9]{1,4}(?:[.,][0-9]{1,3})?$")
_HOURS = re.compile(rf"(?<![0-9.,])({_NUMBER})\s*h(?:ours?|rs?)?(?![a-z])")
_MINUTES = re.compile(r"(?<![0-9.,])([0-9]{1,4})\s*m(?:in(?:ute)?s?)?(?![a-z])")
_AFTER_HOURS = re.compile(r"^[\s,]*(?:and\s+)?([0-5]?[0-9])(?:\s*m(?:in(?:ute)?s?)?)?(?![0-9a-z])")
_ISO_DATE = re.compile(r"^([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?(?![0-9])")
_MONTH_YEAR = re.compile(r"^([a-z]+)\.?\s+([0-9]{4})$")
_MONTHS = {name: number for number, names in enumerate(
    ("jan january", "feb february", "mar march", "apr april", "may", "jun june", "jul july", "aug august",
     "sep sept september", "oct october", "nov november", "dec december"), 1) for name in names.split()}

#: The longest running time IFDB can mean; anything above it is a typo.
MAX_MINUTES = 24 * 60

#: An edit cannot predate its film. A year earlier than the film's still passes:
#: IFDB lists some edits by a festival or premiere date, and catalogues disagree
#: on a film's year by one.
YEAR_TOLERANCE = 1


def release_date(text: Optional[str]) -> Optional[str]:
    """``YYYY-MM-DD`` (or ``YYYY-MM``, ``YYYY``) from IFDB's release date, which
    reads "April 2026", "2026" or an ISO date; None for anything else."""
    t = (text or "").strip().lower()
    iso = _ISO_DATE.match(t)
    if iso:
        return "-".join(part for part in iso.groups() if part)
    month_year = _MONTH_YEAR.match(t)
    if month_year and month_year.group(1) in _MONTHS:
        return f"{month_year.group(2)}-{_MONTHS[month_year.group(1)]:02d}"
    return None


def runtime_minutes(text: Optional[str]) -> Optional[float]:
    """Minutes from IFDB's running time ("1h 45m", "1h45", "1,5h", "105 min", "105", "1:45", "1:45:00"),
    or None when it reads as none or as more than a day."""
    t = (text or "").strip().lower()
    clock = _CLOCK.match(t)
    hours, minutes = _HOURS.search(t), _MINUTES.search(t)
    if clock:
        total = int(clock.group(1)) * 60 + int(clock.group(2))
    elif _PLAIN.match(t):
        total = float(t.replace(",", "."))
    elif hours:
        total = float(hours.group(1).replace(",", ".")) * 60
        after = _AFTER_HOURS.match(t[hours.end():])
        total += int(after.group(1)) if after else 0
    elif minutes:
        total = int(minutes.group(1))
    else:
        return None
    return round(total, 2) if 0 < total <= MAX_MINUTES else None


class PyfaneditSource(CatalogSource):
    name = "pyfanedit"
    priority = 50
    variants_kinds = {"movie": ("tmdb", "imdb"), "series": ("tvdb", "tmdb", "imdb")}

    def variants(self, scheme, value, kind, *, title, year, timeout):
        from metadatarr.resolve.base import all_providers

        provider = all_providers()["pyfanedit"]
        out = []
        for summary in provider.search_title(title):
            extra = variant_extra(summary)
            released = extra.get("fanedit_release_date") or ""
            date = release_date(released)
            made = year_of(date)
            if year and made and made < year - YEAR_TOLERANCE:
                continue
            variant = {
                "type": "fanedit", "name": extra.get("edit_name") or "", "editor": extra.get("faneditor") or "",
                "version": "", "source_formats": [], "released": released, "url": extra.get("fanedit_url") or "",
                "subtype": extra.get("fanedit_subtype") or (summary.fanedit_type or "").lower(),
                "of": {scheme: value},
                **{k: extra[k] for k in ("running_time", "available_in", "release_information") if k in extra},
            }
            out.append(Item(
                kind=kind, title=summary.title, year=made, release_date=date,
                runtime_min=runtime_minutes(extra.get("running_time")), overview=plain_text(extra.get("synopsis")),
                poster_url=extra.get("cover_url") or "", ext_ids=ids(ifdb=summary.fanedit_id),
                extra={"variant": variant},
            ))
        return out


register_source(PyfaneditSource())
