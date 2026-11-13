# Offline metadata layer

The offline layer answers lookups from SQLite files on local disk before it asks a live provider. The files are built from the public parquet datasets of the [LeData](https://huggingface.co/LeData) organisation on the Hugging Face Hub. The layer only reads from the Hub; it never uploads anything. It is off unless `METADATARR_OFFLINE_DIR` names a directory, and with it off every route behaves and answers exactly as it does without the layer.

## Turn it on

Install the parquet reader, point the layer at a directory, and build the sets you want:

```bash
pip install "metadatarr[offline]"
export METADATARR_OFFLINE_DIR=/srv/metadatarr/offline
metadatarr-sync --set tvmaze-shows --set anilist-anime
```

`python -m metadatarr.offline` is the same command. `--list` prints the sets, `--status` prints what is built, `--all` syncs every set and `--force` rebuilds a set whose dataset has not changed. The reading side needs no parquet library; only `metadatarr-sync` does.

A sync asks the Hub for the dataset's head revision and its file list. A set already built from that revision is left alone. Otherwise the missing shards are downloaded one at a time with a pause between files (`METADATARR_OFFLINE_GAP`, 20 seconds by default), each checked against the size and SHA-256 the Hub reports, and then built into one SQLite file. A download that stops resumes from the bytes already on disk the next time. Before anything is fetched, the command checks that the cache disk can hold the missing shards and that the data disk can hold the built file, each with `METADATARR_OFFLINE_MIN_FREE` bytes (1 GiB by default) left over, and refuses to start when it cannot.

The shards go to `METADATARR_OFFLINE_CACHE_DIR`, or to a `metadatarr-ledata` directory inside `HF_HUB_CACHE`, or to `.parquet` inside the data directory. `HF_HOME` is never read. The command only ever creates or removes files under those two directories. A file is built under a temporary name inside the data directory and renamed over the live file when it is complete and its row count matches the shards, so a build that fails leaves the previous file in place. The finished files are in WAL mode with an index on every external id and on the normalised title. Because they use WAL, the directory must be writable for readers; on a read-only mount the files cannot be opened, and the layer falls back to live providers only.

## Sets

Each set maps the dataset's own columns. A set either fronts a live provider, which then answers only when the set has no usable row, or stands alone and adds results no live provider gives.

| Set | Dataset | Serves | Ids |
| --- | --- | --- | --- |
| `tvmaze-shows` | `media-metadata-tvmaze-shows` | `tvmaze` provider | tvmaze, imdb, tvdb, tvrage |
| `anilist-anime` | `media-metadata-anilist-anime` | `anilist` provider | anilist, mal |
| `jikan-manga` | `media-metadata-jikan-manga` | `jikan_manga` provider | mal |
| `librivox-audiobooks` | `media-metadata-librivox-audiobooks` | `librivox` provider | librivox |
| `openlibrary-books` | `media-metadata-openlibrary-books` | `openlibrary` provider | olid, isbn-10, isbn-13 |
| `fanedits` | `media-metadata-fanedits` | `pyfanedit` provider | fanedit, imdb of the film |
| `musicbrainz-artists` | `media-metadata-musicbrainz-artists` | stand-alone | musicbrainz artist |
| `unified-artists` | `media-metadata-unified-artists` | stand-alone | musicbrainz, audiodb, metal archives, progarchives, jazz, classical, bandcamp, soundcloud |
| `artists` | `media-metadata-artists` | stand-alone | the same, without bandcamp and soundcloud |
| `wikidata-entities` | `media-metadata-wikidata-entities` | stand-alone | wikidata |
| `gutenberg-books` | `media-metadata-gutenberg-books` | stand-alone | gutenberg |
| `podcastindex-podcasts` | `media-metadata-podcastindex-podcasts` | stand-alone | apple podcasts, feed url |
| `listennotes-podcasts` | `media-metadata-listennotes-podcasts` | stand-alone | listen notes |
| `steam-games` | `media-metadata-steam-games` | stand-alone | steam app |
| `radiobrowser-stations` | `media-metadata-radiobrowser-stations` | stand-alone | station uuid |
| `metal-archives` | `media-metadata-metal-archives` | stand-alone | metal archives band |
| `progarchives-artists` | `media-metadata-progarchives-artists` | stand-alone | progarchives |
| `jazz-artists` | `media-metadata-jazz-artists` | stand-alone | jazz archives slug |
| `deezer-playlists` | `media-metadata-deezer-playlists` | stand-alone | deezer playlist |
| `ytmusic-playlists` | `media-metadata-ytmusic-playlists` | stand-alone | ytmusic playlist |

Ids that `ExternalIds` has no field for appear under `extra`, for example `steam_appid`.

## How an answer is chosen

A title search for a fronted provider looks the title up in the set, matching it whole after lower-casing, removing accents and punctuation and collapsing spaces, against the title and the alternative names the dataset lists. Several equal names come back best known first (by edition count, popularity or members, whichever the dataset has). The medium of the request must be one the set covers; a request with no medium goes to the live provider.

An id enrichment for a fronted provider that implements one, and a catalogue lookup by `tvmaze`, `tvdb`, `imdb`, `anilist`, `mal`, `librivox`, `openlibrary`, `isbn` or `musicbrainz` id, are answered the same way. A catalogue lookup whose live answer lists children (a series with its seasons, an artist with its albums, an audiobook with its chapters) is answered offline only when the request leaves the children out, as an id-only resolve does; otherwise the live source answers.

A live provider is asked instead when:

- the set is not built, or its file cannot be read (a damaged file is logged once and skipped);
- the set has no row for the request;
- the request carries `refresh=1`;
- the set was built longer ago than `METADATARR_OFFLINE_MAX_AGE` seconds (30 days by default; `0` never expires);
- the request names a provider explicitly.

The stand-alone sets add their matches beside the live ones in candidates and resolve, and their cross references to an enrichment after the live ones, since no live provider competes for them; they are served at any age. An artist is searched by `artist` only when the request has no `title`.

External ids are checked with the same rules as the routes (`check_external_ids`) before they are used, an id that fails is never looked up offline, and every query is parameterised.

## Where the origin shows

A match in `/api/v1/candidates` and in the `accepted` list of a resolve carries `origin`. So do the answers of `/api/v1/lookup` and the id form of `/api/v1/resolve`. It is `{"source": "live"}` for an answer a live provider gave, and for an offline row:

```json
{"source": "offline", "dataset": "LeData/media-metadata-tvmaze-shows",
 "revision": "<dataset revision>", "built_at": "2000-01-01T00:00:00Z"}
```

`/api/v1/enrich` returns a bare `ExternalIds`, so its origin is the `X-Metadatarr-Origin` response header: `live`, or `offline <dataset>@<revision>` for each dataset that contributed. With the layer off, none of these fields or headers is present. Offline items answer with `providers: ["ledata"]`.

## Settings

| Variable | Purpose |
| --- | --- |
| `METADATARR_OFFLINE_DIR` | directory of the SQLite files; unset turns the layer off |
| `METADATARR_OFFLINE_CACHE_DIR` | where parquet shards are downloaded and resumed |
| `METADATARR_OFFLINE_MAX_AGE` | seconds after which a built set counts as stale (default 2592000; `0` = never) |
| `METADATARR_OFFLINE_GAP` | seconds between two downloads (default 20) |
| `METADATARR_OFFLINE_MIN_FREE` | bytes that must stay free after a download or a build (default 1073741824) |
| `HF_TOKEN` | optional Hub token sent with downloads |

## Not covered

The datasets `movie_actors`, `movie_directors`, `movie_writers`, `movie_producers`, `movie_composers` and `WikidataMediaEntities` are CSV files of person-to-film links and of bare name strings. They hold no title, year or per-entity record, so no set maps them. Credits, person and extras questions are always answered live.
