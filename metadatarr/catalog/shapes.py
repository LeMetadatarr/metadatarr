# SPDX-License-Identifier: Apache-2.0
"""The shapes the catalogue routes answer in.

They follow the item / person / credit model of the arrkit apps field for
field, so a client stores an answer without translating it:

- :class:`Item`: ``kind``, ``title``, ``sort_title``, ``original_title``,
  ``year``, ``release_date``, ``runtime_min``, ``overview``, ``poster_url``,
  ``position``, ``ext_ids``, ``extra`` and, in a lookup, ``children``.
- :class:`Person`: ``name``, ``kind`` (person, group or company), ``ext_ids``,
  ``aliases``, ``image_url``, ``sort_name``, ``birth_date``, ``death_date``,
  ``country``, ``bio``, ``extra``.
- :class:`Credit`: ``person``, ``role`` (see :mod:`metadatarr.catalog.roles`),
  ``character``, ``position``, ``note`` and, in a filmography, ``item``.
- :class:`Extra`: a video that belongs to an item (a trailer, a featurette, a
  music video): ``type`` (see :data:`EXTRA_TYPES`), ``type_raw``, ``title``,
  ``site``, ``key``, ``url``, ``language``, ``country``, ``official``,
  ``resolution``, ``runtime_s``, ``published``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

PersonKind = Literal["person", "group", "company"]


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    title: str
    sort_title: str = ""
    original_title: str = ""
    year: Optional[int] = None
    release_date: Optional[str] = None
    runtime_min: Optional[float] = None
    overview: str = ""
    poster_url: str = ""
    position: Optional[float] = None
    ext_ids: Dict[str, str] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)
    children: List["Item"] = Field(default_factory=list)


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: PersonKind = "person"
    ext_ids: Dict[str, str] = Field(default_factory=dict)
    aliases: List[str] = Field(default_factory=list)
    image_url: str = ""
    sort_name: str = ""
    birth_date: Optional[str] = None
    death_date: Optional[str] = None
    country: str = ""
    bio: str = ""
    extra: Dict[str, Any] = Field(default_factory=dict)


class Credit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person: Person
    role: str
    character: str = ""
    position: Optional[int] = None
    note: str = ""
    item: Optional[Item] = None


#: The types an extra is given, the arrkit apps' vocabulary.
EXTRA_TYPES = ("trailer", "teaser", "behind-the-scenes", "making-of", "featurette", "deleted-scene", "interview",
               "clip", "scene", "short", "music-video", "live-session", "other")

#: A provider's own word for a type of extra that is not the vocabulary's word spelt another way.
_EXTRA_WORDS = {"live performance": "live-session"}


def extra_type(word: Optional[str]) -> str:
    """The vocabulary's type for a provider's word, read without case, spaces
    or underscores ("Behind the Scenes" is ``behind-the-scenes``); ``other``
    for a word it has no type for (TMDB's "Bloopers" and "Opening Credits")."""
    w = " ".join((word or "").strip().lower().replace("-", " ").replace("_", " ").split())
    if w.replace(" ", "-") in EXTRA_TYPES:
        return w.replace(" ", "-")
    return _EXTRA_WORDS.get(w, "other")


class Extra(BaseModel):
    """A video that belongs to an item. ``site`` and ``key`` name it on its site
    (``youtube`` and the video id), ``official`` is whether the catalogue marks
    it as the studio's or label's own (``None`` when it does not say),
    ``resolution`` the height the site offers it in, ``runtime_s`` its length
    in seconds and ``published`` the ISO date it appeared."""

    model_config = ConfigDict(extra="forbid")

    type: str
    type_raw: str = ""
    title: str = ""
    site: str = ""
    key: str = ""
    url: str = ""
    language: str = ""
    country: str = ""
    official: Optional[bool] = None
    resolution: Optional[int] = None
    runtime_s: Optional[float] = None
    published: Optional[str] = None


class PersonDetails(BaseModel):
    """A person and their filmography: credits whose ``item`` is set."""

    model_config = ConfigDict(extra="forbid")

    person: Person
    credits: List[Credit] = Field(default_factory=list)


def year_of(date: Optional[str]) -> Optional[int]:
    """The year of an ISO-ish date string (``1999-03-31``, ``1999``), or None."""
    text = (date or "").strip()
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else None


def iso_date(date: Optional[str]) -> Optional[str]:
    """``YYYY-MM-DD`` (or a shorter prefix) from a provider's date or timestamp."""
    text = (date or "").strip()
    if not text or not text[:4].isdigit():
        return None
    return text[:10]


def merge_credits(credits: List[Credit]) -> List[Credit]:
    """One credit per (person, role, character): later duplicates add their
    note to the first one, and positions are renumbered within each role in
    the order the credits arrived."""
    out: List[Credit] = []
    seen: Dict[tuple, Credit] = {}
    counters: Dict[str, int] = {}
    for c in credits:
        ident = next(iter(sorted(c.person.ext_ids.items())), None) or ("name", c.person.name.casefold())
        key = (ident, c.role, c.character)
        first = seen.get(key)
        if first is not None:
            if c.note and c.note not in first.note.split(", "):
                first.note = f"{first.note}, {c.note}" if first.note else c.note
            continue
        seen[key] = c
        c.position = counters.get(c.role, 0)
        counters[c.role] = c.position + 1
        out.append(c)
    return out
