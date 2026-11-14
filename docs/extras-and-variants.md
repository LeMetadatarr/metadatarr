# Extras and variants

Two catalogue routes answer what belongs beside a work rather than inside it.
`GET /api/v1/extras` lists the videos made for an item: trailers, teasers,
featurettes, behind-the-scenes videos, clips and music videos.
`GET /api/v1/variants` lists the versions of a work that its makers never
released, such as fan edits. Both work like the other catalogue routes (see
[Looking things up by identifier](catalog.md)): the same `scheme`, `value`,
`kind`, `provider` and `refresh` parameters, the same errors, the same cache.
A client needs no key of any provider for them.

## Extras

`GET /api/v1/extras?scheme=…&value=…&kind=…` answers:

```json
{"provider": "tmdb",
 "extras": [{"type": "trailer", "type_raw": "Trailer", "title": "Official Trailer", "site": "youtube",
             "key": "abc123", "url": "https://www.youtube.com/watch?v=abc123", "language": "en", "country": "US",
             "official": true, "resolution": 1080, "runtime_s": null, "published": "1999-02-11"}],
 "providers": ["tmdb"], "errors": [], "truncated": false}
```

`provider` names the catalogue that listed the extras. An item the catalogue
knows and that has no videos answers an empty list.

Each extra has these fields:

| Field | Meaning |
| --- | --- |
| `type` | one of trailer, teaser, behind-the-scenes, making-of, featurette, deleted-scene, interview, clip, scene, short, music-video, live-session, other |
| `type_raw` | the catalogue's own word for the type, such as TMDB's "Behind the Scenes" or "Bloopers" |
| `title` | the video's title |
| `site`, `key` | the site that hosts it (`youtube`, `vimeo`) and its id there |
| `url` | its address |
| `language`, `country` | ISO 639-1 and ISO 3166-1 codes, empty when the catalogue does not say |
| `official` | whether the catalogue marks it as the studio's or label's own; `null` when it does not say |
| `resolution` | the height the site offers it in, in pixels |
| `runtime_s` | its length in seconds |
| `published` | the ISO date it appeared |

A word without a type in the vocabulary, such as TMDB's "Bloopers" or
"Opening Credits", is `other`, and the word stays in `type_raw`.

### Which provider answers

| Provider | Kinds and schemes | What it lists |
| --- | --- | --- |
| `tmdb` (needs `TMDB_API_KEY`) | movie by tmdb or imdb; series by tmdb, imdb or tvdb; season by tmdb or tvdb (`<series id>/<season number>`) | every video TMDB has for the movie, series or season, with type, language, country, official flag, resolution and date |
| `skyhook` (no key) | movie by tmdb or imdb | the one YouTube trailer Radarr's metadata proxy names for the movie |
| `discogs` (no key) | album by discogs release id | the videos linked to the release, each a `music-video` with its length; Discogs gives them no type and no official flag |

TMDB is asked first for a movie, since it lists every video; without its key,
or when it fails, the proxy's trailer answers, and a failed TMDB is listed
under `errors`. Without `TMDB_API_KEY`, series and seasons have no provider,
so a question about them is `501` with a message naming `tmdb` as the
unavailable provider.

## Variants

`GET /api/v1/variants?scheme=…&value=…&kind=…&title=…&year=…` answers:

```json
{"variants": [{"kind": "movie", "title": "Example Film: Example Edit", "year": 2010,
               "release_date": "2010-01", "runtime_min": 105.0, "overview": "…",
               "poster_url": "https://fanedit.org/…", "ext_ids": {},
               "extra": {"variant": {"type": "fanedit", "name": "Example Edit", "editor": "Example Editor",
                                     "version": "", "source_formats": [], "released": "January 2010",
                                     "url": "https://fanedit.org/…", "subtype": "fanfix",
                                     "of": {"tmdb": "603"}, "running_time": "1h 45m"}}}],
 "providers": ["pyfanedit"], "errors": [], "truncated": false}
```

Each variant is an item of the work's kind. `extra.variant` holds what the
variant is: `type` (`fanedit`), `name` (the edit's own name, its title after
the work's title), `editor`, `version`, `source_formats`, `released` (the
date as the catalogue writes it), `url` (the page that describes it),
`subtype` (the catalogue's own type, such as `fanfix` or `tv_to_movie`), `of`
(the id the question named) and, when the catalogue gives them,
`running_time`, `available_in` and `release_information` as written there.
`ext_ids.ifdb` is the edit's Internet Fanedit Database id when the catalogue
gives one. `release_date` and `year` read the catalogue's date, which IFDB
writes as a month and year ("April 2026") or a bare year; `release_date` is
then `2026-04` or `2026`. `runtime_min` is empty for a running time that does
not read as minutes or exceeds a day.

The variants are searched by the work's title. `title` and `year` name the
work, and the title you send is at most 200 characters. With `year`, edits released more than
a year before the work are dropped (IFDB's search cannot tell a film from its
remake); an edit without a release date is kept. Without `title`, the work is looked up by its id first (as
`/api/v1/lookup` would), a work no catalogue knows is `404`, and an id no
available provider can look up is `501` with a message asking for the title.

### Which provider answers

| Provider | Kinds and schemes | What it lists |
| --- | --- | --- |
| `pyfanedit` (no key) | movie by tmdb or imdb; series by tvdb, tmdb or imdb | the fan edits the Internet Fanedit Database lists for the work's title: name, faneditor, release date, running time, cover, synopsis and type |

The `pyfanedit` library reads each edit's faneditor, release date, running
time, cover and synopsis from IFDB's search page. It reads no IFDB id there,
so `ext_ids` stays empty until it does, and the formats an edit is available
in and how it is released appear only on the edit's own page, which is not
read; those fields are present only when the search result carries them.

A search of fanedit.org that fails is an error of the answer: `502` with the
failure under `errors`, never an empty list, and it is not cached.

The resolver collects the same fan edits with `include_variants`: `POST
/resolve`, and `POST /api/v1/resolve`, which for an item found by id searches
under the catalogue's title. A failed search is listed in `provider_errors`
(and, on the versioned route, in `errors`).

## Capabilities

`GET /api/v1/providers` lists `extras` and `variants` in each provider's
`capabilities`, as kind to schemes, beside `lookup`, `credits` and `person`.
An empty table means the provider answers neither. A client asks these routes
only when an available provider lists something for them.

```bash
curl -s 'http://localhost:8487/api/v1/extras?scheme=imdb&value=tt0133093&kind=movie'
# → the trailers and featurettes of The Matrix

curl -s 'http://localhost:8487/api/v1/variants?scheme=tmdb&value=11&kind=movie&title=Star%20Wars&year=1977'
# → the fan edits of Star Wars listed on fanedit.org
```

From Python, the same questions go through `catalog.ask`:

```python
from metadatarr import catalog

extras = catalog.ask("extras", "imdb", "tt0133093", "movie").value
edits = catalog.ask("variants", "tmdb", "11", "movie", title="Star Wars", year=1977).value
```

`catalog.ask("variants", …)` needs the title; the HTTP route looks it up when
it is missing.
