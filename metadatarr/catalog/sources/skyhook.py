# SPDX-License-Identifier: Apache-2.0
"""The Servarr metadata proxies, keyless: movies and collections (TMDB data,
from Radarr's proxy), series, seasons and episodes (TVDB data, from Sonarr's
proxy), artists and albums (MusicBrainz data, from Lidarr's proxy).

Sonarr's proxy gives a season no identifier of its own, so a season is named
``<series tvdb id>/<season number>`` under the ``tvdb`` scheme. An album's
tracks come from one of its releases: an official release with the track
count most official releases share, the earliest of those. Track positions
count on across discs; the disc and the place on it are in ``extra``.
"""
from __future__ import annotations

from collections import Counter
from typing import List, Optional

from metadatarr.catalog import _http
from metadatarr.catalog.base import CatalogSource, register_source
from metadatarr.catalog.roles import normalise_role
from metadatarr.catalog.shapes import Credit, Item, Person, iso_date, merge_credits, year_of
from metadatarr.catalog.sources._util import as_int, ids, image, minutes, plain_text

RADARR = "https://radarrapi.servarr.com/v1"
SONARR = "https://skyhook.sonarr.tv/v1/tvdb"
LIDARR = "https://api.lidarr.audio/api/v0.4"


def season_value(series_id, number) -> str:
    return f"{series_id}/{number}"


def parse_season_value(value: str):
    series, _, number = value.partition("/")
    if not (series.isdigit() and number.isdigit()):
        raise ValueError(f"a season is named <series id>/<season number>, not {value!r}")
    return series, int(number)


def _movie(m: dict, position: Optional[float] = None) -> Item:
    collection = m.get("Collection") or {}
    extra = {k: v for k, v in {
        "genres": m.get("Genres") or [],
        "studio": m.get("Studio") or "",
        "original_language": m.get("OriginalLanguage") or "",
        "collection": ids(tmdb=collection.get("TmdbId"), name=collection.get("Name")),
        "status": m.get("Status") or "",
    }.items() if v}
    return Item(
        kind="movie", title=m.get("Title") or "", original_title=m.get("OriginalTitle") or "",
        year=as_int(m.get("Year")), release_date=iso_date(m.get("InCinema") or m.get("Premier")),
        runtime_min=minutes(m.get("Runtime")), overview=plain_text(m.get("Overview")),
        poster_url=image(m.get("Images"), "Poster"), position=position,
        ext_ids=ids(tmdb=m.get("TmdbId"), imdb=m.get("ImdbId")), extra=extra,
    )


def _date_key(date: Optional[str]) -> str:
    """A release date for sorting; a missing date or the proxy's 0001-01-01 placeholder sorts last."""
    return "9999" if not date or date.startswith("0001") else date


def numbered_tracks(tracks: List[Item]) -> List[Item]:
    """Tracks given in disc order with ``extra.medium`` and ``extra.disc_position``
    numbered 1..n across every disc, so ``position`` orders a whole album."""
    for n, track in enumerate(tracks, 1):
        track.position = n
    return tracks


def _season_title(number: int) -> str:
    return "Specials" if number == 0 else f"Season {number}"


class SkyhookSource(CatalogSource):
    name = "skyhook"
    priority = 10
    lookup_kinds = {"movie": ("tmdb", "imdb"), "collection": ("tmdb",), "series": ("tvdb",),
                    "season": ("tvdb",), "artist": ("musicbrainz",), "album": ("musicbrainz",)}
    children_kinds = frozenset({"collection", "series", "season", "artist", "album"})
    credits_kinds = {"movie": ("tmdb", "imdb"), "series": ("tvdb",)}

    # -- movies ---------------------------------------------------------------

    def _get_movie(self, scheme: str, value: str, timeout: float) -> Optional[dict]:
        path = f"{RADARR}/movie/imdb/{value}" if scheme == "imdb" else f"{RADARR}/movie/{value}"
        data = _http.get_json(path, timeout=timeout)
        if isinstance(data, list):
            data = data[0] if data else None
        return data if isinstance(data, dict) and data.get("TmdbId") else None

    # -- series ---------------------------------------------------------------

    def _get_show(self, series_id: str, timeout: float) -> Optional[dict]:
        if not series_id.isdigit():
            return None
        data = _http.get_json(f"{SONARR}/shows/en/{series_id}", timeout=timeout)
        return data if isinstance(data, dict) and data.get("tvdbId") else None

    def _series(self, show: dict, children: bool) -> Item:
        sid = show.get("tvdbId")
        episodes = show.get("episodes") or []
        item = Item(
            kind="series", title=show.get("title") or "", year=year_of(show.get("firstAired")),
            release_date=iso_date(show.get("firstAired")), runtime_min=minutes(show.get("runtime")),
            overview=plain_text(show.get("overview")), poster_url=image(show.get("images"), "Poster", key="url",
                                                                        type_key="coverType"),
            ext_ids=ids(tvdb=sid, tmdb=show.get("tmdbId"), imdb=show.get("imdbId"), tvmaze=show.get("tvMazeId")),
            extra={k: v for k, v in {"network": show.get("network") or show.get("originalNetwork"),
                                     "status": show.get("status"), "genres": show.get("genres") or [],
                                     "original_language": show.get("originalLanguage"),
                                     "content_rating": show.get("contentRating")}.items() if v},
        )
        if children:
            for s in sorted(show.get("seasons") or [], key=lambda s: s.get("seasonNumber") or 0):
                item.children.append(self._season(show, s, episodes, False))
        return item

    def _season(self, show: dict, season: dict, episodes: List[dict], children: bool) -> Item:
        number = as_int(season.get("seasonNumber")) or 0
        own = [e for e in episodes if as_int(e.get("seasonNumber")) == number]
        dates = sorted(d for d in (iso_date(e.get("airDate")) for e in own) if d)
        item = Item(
            kind="season", title=_season_title(number), position=number,
            year=year_of(dates[0]) if dates else None, release_date=dates[0] if dates else None,
            poster_url=image(season.get("images"), "Poster", key="url", type_key="coverType"),
            ext_ids={"tvdb": season_value(show.get("tvdbId"), number)},
            extra={"episode_count": len(own), "series": ids(tvdb=show.get("tvdbId"))},
        )
        if children:
            for e in sorted(own, key=lambda e: as_int(e.get("episodeNumber")) or 0):
                extra = {"season": number}
                if e.get("absoluteEpisodeNumber") is not None:
                    extra["absolute_episode"] = e["absoluteEpisodeNumber"]
                item.children.append(Item(
                    kind="episode", title=e.get("title") or "", position=as_int(e.get("episodeNumber")),
                    year=year_of(e.get("airDate")), release_date=iso_date(e.get("airDate")),
                    runtime_min=minutes(e.get("runtime")), overview=plain_text(e.get("overview")),
                    poster_url=e.get("image") or "", ext_ids=ids(tvdb=e.get("tvdbId")), extra=extra,
                ))
        return item

    # -- music ----------------------------------------------------------------

    def _artist(self, a: dict, children: bool) -> Item:
        item = Item(
            kind="artist", title=a.get("artistname") or "", sort_title=a.get("sortname") or "",
            overview=plain_text(a.get("overview")), poster_url=image(a.get("images"), "Poster"),
            ext_ids=ids(musicbrainz=a.get("id")),
            extra={k: v for k, v in {"type": a.get("type"), "status": a.get("status"),
                                     "disambiguation": a.get("disambiguation"),
                                     "aliases": a.get("artistaliases") or [],
                                     "genres": a.get("genres") or []}.items() if v},
        )
        if children:
            albums = sorted(a.get("Albums") or [], key=lambda x: (x.get("ReleaseDate") or "9999", x.get("Title") or ""))
            for al in albums:
                item.children.append(Item(
                    kind="album", title=al.get("Title") or "", year=year_of(al.get("ReleaseDate")),
                    release_date=iso_date(al.get("ReleaseDate")), ext_ids=ids(musicbrainz=al.get("Id")),
                    extra={k: v for k, v in {"type": al.get("Type"),
                                             "secondary_types": al.get("SecondaryTypes") or []}.items() if v},
                ))
        return item

    @staticmethod
    def _pick_release(releases: List[dict]) -> Optional[dict]:
        """The release whose tracks stand for the album: an official one with
        the track count most official releases share, the earliest of those."""
        official = [r for r in releases if (r.get("Status") or "").lower() == "official"] or releases
        counts = Counter(r.get("TrackCount") for r in official)
        ranked = sorted(official, key=lambda r: (-counts[r.get("TrackCount")], _date_key(r.get("ReleaseDate"))))
        return ranked[0] if ranked else None

    def _album(self, al: dict, children: bool) -> Item:
        artist = next(iter(al.get("artists") or []), {})
        release = self._pick_release(al.get("Releases") or [])
        extra = {k: v for k, v in {
            "type": al.get("type"), "secondary_types": al.get("secondarytypes") or [],
            "genres": al.get("genres") or [],
            "artist": ids(name=artist.get("artistname"), musicbrainz=artist.get("id") or al.get("artistid")),
            "release": ids(musicbrainz=(release or {}).get("Id"), title=(release or {}).get("Title")),
        }.items() if v}
        item = Item(
            kind="album", title=al.get("title") or "", year=year_of(al.get("releasedate")),
            release_date=iso_date(al.get("releasedate")), overview=plain_text(al.get("overview")),
            poster_url=image(al.get("images"), "Cover", "Poster"), ext_ids=ids(musicbrainz=al.get("id")),
            extra=extra,
        )
        if children and release:
            tracks = sorted(release.get("Tracks") or [],
                            key=lambda t: (t.get("MediumNumber") or 1, t.get("TrackPosition") or 0))
            item.children = numbered_tracks([Item(
                kind="track", title=t.get("TrackName") or "",
                runtime_min=minutes(t.get("DurationMs"), 1 / 60000),
                ext_ids=ids(musicbrainz=t.get("RecordingId")),
                extra={k: v for k, v in {"medium": t.get("MediumNumber") or 1,
                                         "disc_position": as_int(t.get("TrackPosition")),
                                         "number": t.get("TrackNumber"),
                                         "musicbrainz_track": t.get("Id")}.items() if v},
            ) for t in tracks])
        return item

    # -- questions --------------------------------------------------------------

    def lookup(self, scheme, value, kind, *, children, timeout):
        if kind == "movie":
            m = self._get_movie(scheme, value, timeout)
            return _movie(m) if m else None
        if kind == "collection":
            if not value.isdigit():
                return None
            c = _http.get_json(f"{RADARR}/movie/collection/{value}", timeout=timeout)
            if not isinstance(c, dict) or not c.get("TmdbId"):
                return None
            parts = sorted(c.get("Parts") or [], key=lambda p: (p.get("Year") or 9999, p.get("Title") or ""))
            years = [p.get("Year") for p in parts if p.get("Year")]
            item = Item(kind="collection", title=c.get("Name") or "", overview=plain_text(c.get("Overview")),
                        poster_url=image(c.get("Images"), "Poster"), year=min(years) if years else None,
                        ext_ids=ids(tmdb=c.get("TmdbId")))
            if children:
                item.children = [_movie(p, n) for n, p in enumerate(parts, 1)]
            return item
        if kind == "series":
            show = self._get_show(value, timeout)
            return self._series(show, children) if show else None
        if kind == "season":
            series_id, number = parse_season_value(value)
            show = self._get_show(series_id, timeout)
            if not show:
                return None
            season = next((s for s in show.get("seasons") or [] if as_int(s.get("seasonNumber")) == number), None)
            return self._season(show, season, show.get("episodes") or [], children) if season else None
        if kind == "artist":
            a = _http.get_json(f"{LIDARR}/artist/{value}", timeout=timeout)
            return self._artist(a, children) if isinstance(a, dict) and a.get("id") else None
        if kind == "album":
            al = _http.get_json(f"{LIDARR}/album/{value}", timeout=timeout)
            return self._album(al, children) if isinstance(al, dict) and al.get("id") else None
        return None

    def credits(self, scheme, value, kind, *, timeout):
        if kind == "movie":
            m = self._get_movie(scheme, value, timeout)
            if not m:
                return None
            block = m.get("Credits") or {}
            out: List[Credit] = []
            for c in sorted(block.get("Cast") or [], key=lambda c: c.get("Order") or 0):
                if c.get("Name"):
                    out.append(Credit(person=Person(name=c["Name"], ext_ids=ids(tmdb=c.get("TmdbId")),
                                                    image_url=image(c.get("Images"), "Headshot")),
                                      role="actor", character=c.get("Character") or ""))
            for c in block.get("Crew") or []:
                role = normalise_role(c.get("Job") or c.get("Department"))
                if c.get("Name") and role:
                    out.append(Credit(person=Person(name=c["Name"], ext_ids=ids(tmdb=c.get("TmdbId")),
                                                    image_url=image(c.get("Images"), "Headshot")),
                                      role=role))
            if m.get("Studio"):
                out.append(Credit(person=Person(name=m["Studio"], kind="company"), role="studio"))
            return merge_credits(out)
        if kind == "series":
            show = self._get_show(value, timeout)
            if not show:
                return None
            out = [Credit(person=Person(name=a["name"], image_url=a.get("image") or ""), role="actor",
                          character=a.get("character") or "")
                   for a in show.get("actors") or [] if a.get("name")]
            network = show.get("originalNetwork") or show.get("network")
            if network:
                out.append(Credit(person=Person(name=network, kind="company"), role="network"))
            return merge_credits(out)
        return None


register_source(SkyhookSource())
