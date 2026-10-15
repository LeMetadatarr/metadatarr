# Looking things up by identifier

The resolver answers "what is this?" from a title. The catalogue routes answer
"tell me about this id": the details of an item with its children one level
down, the people credited on it, and a person with their filmography. A client
needs no API key of any provider for them. Keys that a provider needs, such as
`TMDB_API_KEY`, stay in metadatarr's own environment, and a provider without its
key is simply not available.

Every answer comes in the same shapes, which follow the item, person and
credit model of the arrkit apps field for field, so a client can store an
answer without translating it.

## The routes

`GET /api/v1/lookup?scheme=…&value=…&kind=…` returns `{"item", "providers",
"errors", "truncated"}`. The item carries its children one level down:

| Kind | Children |
| --- | --- |
| `series` | seasons |
| `season` | episodes |
| `show` | episodes |
| `artist` | albums |
| `album` | tracks |
| `author` | books |
| `audiobook` | chapters |
| `collection` | movies |

To walk further, look a child up by one of its own ids. `movie`, `episode`,
`track`, `book` and `chapter` items have no children.

`GET /api/v1/credits?scheme=…&value=…&kind=…` returns `{"credits", "providers",
"errors", "truncated"}`: the people, groups and companies credited on the item.

`GET /api/v1/person?scheme=…&value=…` returns `{"person", "credits",
"providers", "errors", "truncated"}`. Each credit of a person carries the `item` it is on,
so the credits are the person's filmography.

`kind` is optional when the scheme implies it: `tmdb` and `imdb` default to
`movie`, `tvdb` and `tvmaze` to `series`, `musicbrainz` to `album`, `anilist`
and `mal` to `series`, `isbn` to `book`, `librivox` to `audiobook`,
`apple_podcasts` to `show`, and an Open Library id to `author` when it ends in
`A` and to `book` otherwise. An IMDb id of a series needs `kind=series`.
AniList knows whether an anime is a movie or a series, so without `kind` an
AniList or MAL lookup answers with the kind AniList records; a `kind` given by
the caller is kept.

`truncated` is `true` when a provider stopped before the end of what its
catalogue holds, for instance at AniList's page limit (see below).

`provider=` asks one provider only, by its name in `/providers`.

A scheme names the catalogue, and the kind picks the record inside it: a TMDB
id is a movie id for a movie and a TV id for a series; a MusicBrainz id is an
artist, release-group or recording id for an artist, album or track.

Two catalogues give a season no id of their own: Sonarr's proxy and TMDB. A
season from them is named `<series id>/<season number>` under the series'
scheme, for example `tvdb` `81189/1`, and a lookup of kind `season` takes that
value. TVmaze seasons have their own ids.

An Open Library book is a work. Looked up by an edition id or an ISBN, it
answers with the work under `openlibrary` and the edition under
`openlibrary_edition`.

## The shapes

An item has `kind`, `title`, `sort_title`, `original_title`, `year`,
`release_date` (ISO date), `runtime_min`, `overview` (plain text),
`poster_url`, `position` (season, episode, track or chapter number; a track's
position counts on across the discs of an album, and `extra.medium` and
`extra.disc_position` give the disc and the place on it),
`ext_ids` (scheme to value), `extra` (what only some providers know, such as
genres, network, the release the tracks came from) and `children`.

A person has `name`, `kind` (`person`, `group` or `company`), `ext_ids`,
`aliases`, `image_url`, `sort_name`, `birth_date`, `death_date`, `country`,
`bio` and `extra`.

A credit has `person`, `role`, `character` (the part played, for actor and
voice-actor credits), `position` (billing order within the role), `note` and,
in a filmography, `item`. One person has one credit per role and character;
the instruments of a musician or the chapters of a narrator are joined in the
note.

## Roles

Providers describe credits in their own words. Each word is mapped onto a
published vocabulary:

| Group | Roles |
| --- | --- |
| Cast | actor, voice-actor, narrator, host, guest, performer, self |
| Writing | writer, screenwriter, author, lyricist, translator, adapted-from |
| Direction and production | director, creator, producer, executive-producer, showrunner, audio-director, sound-designer |
| Music | artist, composer, conductor, arranger, producer-music, featured-artist |
| Craft | cinematographer, editor, illustrator, cover-artist, mixer, mastering |
| Companies | studio, label, publisher, network, distributor |

"Original Music Composer" becomes `composer`, "Director of Photography"
`cinematographer`, AniList's "Series Composition" `writer` and "Original
Creator" `adapted-from`, MusicBrainz's "producer" `producer-music` and its
"instrument" and "vocal" `performer`. Any job about casting ("ADR Voice
Casting", "Casting Director") is `casting`, and a voice or dub director is
`audio-director`. A crew job is never read as `voice-actor` because it
mentions a voice; only a cast entry is. A word outside the vocabulary is kept,
lower-cased with hyphens (`key-animation`), because clients may add roles of
their own. The table and the mapping are in `metadatarr.catalog.roles`.

## What each provider answers

`GET /api/v1/providers` lists, for every provider, a `capabilities` object:
`lookup` and `credits` map an item kind to the schemes they take, `children`
lists the kinds whose lookup carries children, and `person` lists the schemes
a person question takes. `extras` and `variants` map a kind to the schemes of
the routes in [Extras and variants](extras-and-variants.md). Empty tables
mean the provider answers none of them.

| Provider | Lookup (and children) | Credits | Person |
| --- | --- | --- | --- |
| `skyhook` (Servarr proxies, no key) | movie by tmdb or imdb; collection by tmdb, with movies; series by tvdb, with seasons; season by tvdb, with episodes; artist by musicbrainz, with albums; album by musicbrainz, with tracks | movie by tmdb or imdb (cast with characters, crew, studio); series by tvdb (cast with characters, network) | no |
| `tmdb` (needs `TMDB_API_KEY`) | movie by tmdb or imdb; collection, with movies; series by tmdb or imdb, with seasons; season by tmdb, with episodes | movie and series by tmdb or imdb (cast, crew, creators, networks, studios) | by tmdb or imdb, with movie and TV credits |
| `tvmaze` (no key) | series by tvmaze, tvdb or imdb, with seasons; season by tvmaze, with episodes | series by tvmaze, tvdb or imdb (cast, voice and self roles, crew, network) | by tvmaze, with cast and crew credits |
| `musicbrainz` (no key) | artist, with release groups; album (release group or release), with the tracks of one release; track (recording) | album (artist credit, release relationships, labels); track (artist credit, performers with instruments, producers, engineers, the work's writers and composers) | by musicbrainz, with release groups |
| `anilist` (no key) | anime series or movie by anilist or mal; no children, as AniList lists no episodes | characters with voice actors in every language AniList has, staff, studios; at most 10 pages of 25 | by anilist (staff), with voice roles and staff roles; at most 10 pages of 25 each |
| `openlibrary` (no key) | author, with works; book by work id, edition id or ISBN | book: authors, edition contributors, publishers | by openlibrary author id, with works |
| `apple_podcasts` (no key) | show by its Apple id, with the episodes of its RSS feed | show: the feed's `podcast:person` tags; a feed without them gives its author as `creator` | no |
| `librivox` (no key) | audiobook, with chapters | authors, translators, readers as narrators with the chapters each read | no |

AniList answers 25 characters, staff or media per page and allows 30 requests
a minute, so metadatarr spaces its AniList requests two seconds apart. It reads
at most 10 pages, and stops once 60% of the provider timeout has passed: with
the default 10 seconds that is four pages, 100 entries per connection. An
answer cut there has `truncated: true` and is cached like any other. A later
page that fails, or that AniList refuses with 429, also ends the paging; the
answer keeps the pages read, has `truncated: true`, lists the failure under
`errors`, and is neither cached nor sent as cacheable. After a 429, no AniList
request is sent until its Retry-After has passed. A long-running series or a
prolific voice actor (several hundred roles) is cut this way.

Every other provider answers none of these questions. The resolver keeps
using all of them for title resolves.

An album's tracks come from one of its releases. The Servarr proxy picks an
official release with the track count most official releases share, the
earliest of those; MusicBrainz picks the earliest official release. The chosen
release is named under `extra.release`.

## Errors

A question that no available provider can answer is `501`
`{"error": "not supported", "provider": …, "message": …}`, where `provider`
is the provider named with `provider=` or `null`. This covers an unknown
scheme, a kind a provider has no data for, and a provider whose key is not
configured. An empty `200` is never sent for a question that was not asked.

An id that every asked provider says it does not know is `404`
`{"error": "not found", "providers": […], "errors": […]}`. When every asked
provider failed, the answer is `502` `{"error": "upstream failed", …}`. A
malformed question (an unknown kind, an empty value) is `422`
`{"error": "invalid request", …}`, and an id its scheme cannot hold (a TMDB,
TVDB, TVmaze, AniList, MAL, LibriVox or Apple id that is not a positive number
in range, a season not named `<id>/<number>`) is `422` `{"error": "invalid id",
…}`, sent before any provider is asked.

## Failure isolation, timeouts and caching

The providers that can answer are asked one after the other in a fixed
priority order; the first that knows the id answers, and `providers` names it.
A provider that fails or does not answer within its timeout is listed under
`errors` with its name, the exception type and the message, and the next one
is asked, so one provider being down never fails the request. A request URL
inside an error message has its credential parameters masked.

Answers are kept in memory for `METADATARR_CATALOG_CACHE_TTL` seconds (default
3600), at most `METADATARR_CATALOG_CACHE_SIZE` of them (default 1000; `0`
turns the cache off). A "not found", a failure, and an answer given while a
better provider failed are never kept. `METADATARR_CATALOG_TIMEOUT` is the
time each provider gets (default 10 seconds).

A `200` carries an `ETag` and `Cache-Control: public, max-age=<cache TTL>`
(`private` when API keys are on), or `no-cache` when a provider failed on the
way to the answer. A request with a matching `If-None-Match` gets `304`.
`?refresh=1` asks the providers again, skipping this cache and the HTTP disk
cache, and keeps the new answer. Errors are sent with `no-store`.

## Resolving with ids

`POST /api/v1/resolve` takes the `Signals` body of the unversioned
`POST /resolve` plus two fields: `ids`, a map of scheme to value, and `kind`.
Either a title or at least one id is needed.

When a provider can look one of the ids up, that item is the answer. With ids
alone its confidence is 1.0, meaning the ids were found in a catalogue. With a
title as well, the confidence is how well the title and year agree with the
catalogue's. When another of the given ids contradicts the catalogue's, the
confidence is halved and the scheme is listed in `match.id_conflicts`. An id
the catalogue holds under another scheme, such as an Open Library edition id
given as `openlibrary`, agrees with the item.

When no provider can look the ids up, a title resolve runs as usual, except
that a candidate carrying one of the given ids with a different value is
dropped (listed in `dropped` and `conflicts`) and a candidate carrying one with
the same value has its confidence raised to at least 0.95.

The answer is the `ResolveResult` of the unversioned route plus `match`
(`item`, `confidence`, `source`, `credits`, `id_conflicts`, in the shapes
above), `providers` (the providers that contributed), `errors` (the providers
that failed) and `unsupported` (the schemes no provider could look up). With
ids alone, ids that no provider can look up are `501` and ids no catalogue
knows are `404`.

```bash
curl -s -X POST http://localhost:8487/api/v1/resolve \
  -H 'Content-Type: application/json' \
  -d '{"ids": {"imdb": "tt0133093"}, "kind": "movie"}'
# → match.item.title "The Matrix", match.confidence 1.0, providers ["skyhook"]

curl -s 'http://localhost:8487/api/v1/lookup?scheme=tvdb&value=81189/1&kind=season'
# → the first season of Breaking Bad with its episodes

curl -s 'http://localhost:8487/api/v1/credits?scheme=anilist&value=1&kind=series'
# → Cowboy Bebop's characters and voice actors, staff and studios
```

The unversioned `POST /resolve` keeps its original request model and refuses
`ids`.

## From Python

The same questions are available without the server:

```python
from metadatarr import catalog

answer = catalog.ask("lookup", "musicbrainz", "b1392450-e666-3926-a536-22c65f834433", "album")
print(answer.value.title, [t.title for t in answer.value.children], answer.providers, answer.errors)
```

`catalog.ask` raises `catalog.NotSupported` when no available provider can
answer and `ValueError` for a malformed question.
