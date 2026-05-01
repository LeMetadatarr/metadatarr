# AudioDBClient

Wraps [TheAudioDB](https://www.theaudiodb.com/api_guide.php) — a free,
unauthenticated music metadata API. Uses the public test key `123` (no
account or env var required).

## Endpoints covered

| Method                     | Upstream                | Returns                |
| -------------------------- | ----------------------- | ---------------------- |
| `search_artist(name)`      | `search.php?s=`         | `List[AudioDBArtist]`  |
| `get_artist(id)`           | `artist.php?i=`         | `AudioDBArtist`        |
| `get_artist_by_mbid(mbid)` | `artist-mb.php?i=`      | `AudioDBArtist`        |
| `search_album(artist[, album])` | `searchalbum.php`  | `List[AudioDBAlbum]`   |
| `get_album(id)`            | `album.php?i=`          | `AudioDBAlbum`         |
| `get_album_by_mbid(mbid)`  | `album-mb.php?i=`       | `AudioDBAlbum`         |
| `discography(artist)`      | `discography.php`       | `List[AudioDBAlbum]` (year + name) |
| `search_track(artist, title)` | `searchtrack.php`    | `List[AudioDBTrack]`   |
| `get_track(id)`            | `track.php?h=`          | `AudioDBTrack`         |
| `get_track_by_mbid(mbid)`  | `track-mb.php?i=`       | `AudioDBTrack`         |

## Example

```python
from metadatarr import AudioDBClient

c = AudioDBClient()

artist = c.search_artist("Daft Punk")[0]
print(artist.name, artist.musicbrainz_id, artist.formed_year)

for album in c.discography("Daft Punk"):
    print(album.year, album.name)
```

## Notes

- All methods return `[]` / `None` on network errors or empty payloads.
- Album IDs and track IDs in `AudioDBTrack`/`AudioDBAlbum` are AudioDB's own
  numeric ids — string-typed at the model level. MusicBrainz ids are
  separately exposed as `musicbrainz_id` / `musicbrainz_artist_id` /
  `musicbrainz_album_id`.
- Free-tier `discography.php` returns only album name + year.
