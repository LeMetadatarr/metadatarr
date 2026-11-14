# SPDX-License-Identifier: Apache-2.0
"""Apple Podcasts, keyless: a show by its Apple id, its episodes and its people.

The show's details come from the iTunes lookup API; the episodes and the
people come from the show's own RSS feed. People are read from the Podcasting
2.0 ``podcast:person`` tags (role and group as the feed gives them); a feed
without them yields its ``itunes:author`` as the show's creator."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple

from metadatarr.catalog import _http
from metadatarr.catalog.base import CatalogSource, register_source
from metadatarr.catalog.roles import normalise_role
from metadatarr.catalog.shapes import Credit, Item, Person, merge_credits, year_of
from metadatarr.catalog.sources._util import as_int, ids, plain_text

LOOKUP = "https://itunes.apple.com/lookup"

NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
# Feeds declare the Podcasting 2.0 namespace under either of these URIs.
PODCAST_PERSON_TAGS = {
    "{https://podcastindex.org/namespace/1.0}person",
    "{https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/1.0.md}person",
}
MAX_EPISODES = 2000


def _tag(ns: str, name: str) -> str:
    return f"{{{NS[ns]}}}{name}"


def _date(text: Optional[str]) -> Optional[str]:
    try:
        return parsedate_to_datetime(text).date().isoformat() if text else None
    except (TypeError, ValueError):
        return None


def _duration(text: Optional[str]) -> Optional[float]:
    """Minutes from an ``itunes:duration`` of seconds or ``[hh:]mm:ss``."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return None
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return round(seconds / 60, 2) if seconds > 0 else None


def _persons(element) -> List[Tuple[str, str, str, str]]:
    """(name, role, group, image) of each ``podcast:person`` directly under ``element``."""
    out = []
    for p in (child for child in element if child.tag in PODCAST_PERSON_TAGS):
        name = (p.text or "").strip()
        if name:
            out.append((name, p.get("role") or "host", p.get("group") or "", p.get("img") or ""))
    return out


class Feed:
    """What one RSS feed says: channel fields, channel people and episodes."""

    def __init__(self) -> None:
        self.title = ""
        self.description = ""
        self.author = ""
        self.image = ""
        self.people: List[Tuple[str, str, str, str]] = []
        self.episodes: List[Item] = []
        self.episode_people: List[Tuple[str, str, str, str]] = []


def _read_channel(feed: Feed, el) -> None:
    feed.title = (el.findtext("title") or "").strip()
    feed.description = plain_text(el.findtext("description") or el.findtext(_tag("itunes", "summary")))
    feed.author = (el.findtext(_tag("itunes", "author")) or "").strip()
    img = el.find(_tag("itunes", "image"))
    feed.image = img.get("href") if img is not None and img.get("href") else ""
    feed.people = _persons(el)


def _episode(el) -> Item:
    enclosure = el.find("enclosure")
    extra = {k: v for k, v in {
        "season": as_int(el.findtext(_tag("itunes", "season"))), "guid": (el.findtext("guid") or "").strip(),
        "episode_type": el.findtext(_tag("itunes", "episodeType")),
        "enclosure_url": enclosure.get("url") if enclosure is not None else None}.items() if v}
    date = _date(el.findtext("pubDate"))
    return Item(
        kind="episode", title=(el.findtext("title") or "").strip(),
        position=as_int(el.findtext(_tag("itunes", "episode"))), release_date=date, year=year_of(date),
        runtime_min=_duration(el.findtext(_tag("itunes", "duration"))),
        overview=plain_text(el.findtext("description") or el.findtext(_tag("itunes", "summary")), 2000),
        extra=extra,
    )


def parse_feed(body: bytes, max_episodes: int = MAX_EPISODES) -> Feed:
    """Read a feed; a feed cut short by the size limit keeps what was read
    before the cut. Episodes come oldest first."""
    feed = Feed()
    parser = ET.XMLPullParser(events=("start", "end"))
    try:
        parser.feed(body)
        parser.close()
    except ET.ParseError:
        pass
    channel = None
    for event, el in parser.read_events():
        if event == "start":
            if el.tag == "channel":
                channel = el
            elif el.tag == "item" and channel is not None and not feed.title:
                _read_channel(feed, channel)
            continue
        if el.tag == "item":
            if len(feed.episodes) < max_episodes:
                feed.episodes.append(_episode(el))
                feed.episode_people.extend(_persons(el))
            el.clear()
        elif el.tag == "channel":
            _read_channel(feed, el)
    if channel is not None and not feed.title:
        _read_channel(feed, channel)
    if _newest_first(feed.episodes):
        feed.episodes.reverse()
    return feed


def _newest_first(episodes: List[Item]) -> bool:
    dated = [e.release_date for e in episodes if e.release_date]
    return len(dated) > 1 and dated[0] > dated[-1]


class ApplePodcastsSource(CatalogSource):
    name = "apple_podcasts"
    priority = 10
    lookup_kinds = {"show": ("apple_podcasts",)}
    children_kinds = frozenset({"show"})
    credits_kinds = {"show": ("apple_podcasts",)}

    def _show(self, value: str, timeout: float) -> Optional[dict]:
        if not value.isdigit():
            return None
        data = _http.get_json(LOOKUP, params={"id": value, "entity": "podcast"}, timeout=timeout) or {}
        return next((r for r in data.get("results") or []
                     if str(r.get("collectionId")) == value and r.get("kind") == "podcast"), None)

    def _feed(self, show: dict, timeout: float) -> Optional[Feed]:
        url = show.get("feedUrl")
        if not url:
            return None
        body = _http.request("GET", url, timeout=timeout, headers={"Accept": "application/rss+xml, */*"})
        return parse_feed(body) if body else None

    def lookup(self, scheme, value, kind, *, children, timeout):
        show = self._show(value, timeout)
        if show is None:
            return None
        item = Item(
            kind="show", title=show.get("collectionName") or "",
            poster_url=show.get("artworkUrl600") or show.get("artworkUrl100") or "",
            ext_ids=ids(apple_podcasts=show.get("collectionId")),
            extra={k: v for k, v in {"feed_url": show.get("feedUrl"), "author": show.get("artistName"),
                                     "genres": [g for g in show.get("genres") or [] if g != "Podcasts"],
                                     "episode_count": show.get("trackCount")}.items() if v},
        )
        feed = self._feed(show, timeout)
        if feed is not None:
            item.overview = feed.description
            if feed.episodes:
                first = next((e.release_date for e in feed.episodes if e.release_date), None)
                item.release_date, item.year = first, year_of(first)
            if children:
                item.children = feed.episodes
        return item

    def credits(self, scheme, value, kind, *, timeout):
        show = self._show(value, timeout)
        if show is None:
            return None
        feed = self._feed(show, timeout)
        if feed is None:
            return []
        out: List[Credit] = []
        for name, role, group, img in feed.people:
            out.append(Credit(person=Person(name=name, image_url=img),
                              role=normalise_role(role, cast=group == "cast") or "host"))
        show_level = {(n, r) for n, r, _g, _i in feed.people}
        appearances: Dict[Tuple[str, str], int] = Counter(
            (n, r) for n, r, _g, _i in feed.episode_people if (n, r) not in show_level)
        groups = {(n, r): g for n, r, g, _i in feed.episode_people}
        images = {(n, r): i for n, r, _g, i in feed.episode_people}
        for (name, role), count in sorted(appearances.items(), key=lambda kv: -kv[1]):
            note = f"{count} episode" + ("s" if count != 1 else "")
            out.append(Credit(person=Person(name=name, image_url=images[(name, role)]),
                              role=normalise_role(role, cast=groups[(name, role)] == "cast") or "guest", note=note))
        if not out and (feed.author or show.get("artistName")):
            out.append(Credit(person=Person(name=feed.author or show["artistName"]), role="creator",
                              note="feed author"))
        return merge_credits(out)


register_source(ApplePodcastsSource())
