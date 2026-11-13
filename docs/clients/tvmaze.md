# TVmazeClient

Wraps [TVmaze's public API](https://www.tvmaze.com/api). No authentication.
Rate limit (unauthenticated): 20 requests / 10 seconds.

## Endpoints covered

| Method                          | Upstream                  | Returns                |
| ------------------------------- | ------------------------- | ---------------------- |
| `search_shows(query)`           | `/search/shows`           | `List[TVmazeShow]`     |
| `singlesearch(query)`           | `/singlesearch/shows`     | `TVmazeShow`           |
| `get_show(tvmaze_id)`           | `/shows/{id}`             | `TVmazeShow`           |
| `lookup_by_thetvdb(thetvdb_id)` | `/lookup/shows?thetvdb=`  | `TVmazeShow`           |

| Method                          | Upstream                  | Returns                |
| --------------------------------- | ------------------------- | ---------------------- |
| `lookup_by_imdb(imdb_id)`       | `/lookup/shows?imdb=`     | `TVmazeShow`           |
| `get_seasons(tvmaze_id)`        | `/shows/{id}/seasons`     | `List[TVmazeSeason]`   |
| `get_cast(tvmaze_id)`           | `/shows/{id}/cast`        | `List[TVmazeCastMember]` |
| `search_people(query)`          | `/search/people`          | `List[TVmazePerson]`   |

## Example

```python
from metadatarr import TVmazeClient

c = TVmazeClient()

show = c.singlesearch("The Boys")
print(show.id, show.name, show.premiered)
print("imdb=", show.externals.imdb if show.externals else None)

for season in c.get_seasons(show.id):
    print(f"S{season.number}  episodes={season.episode_order}")

for member in c.get_cast(show.id):
    name = member.person.name if member.person else "?"
    print(f"  {name} as {member.character_name}")
```

## Notes

- `get_show` / `lookup_by_*` / `singlesearch` return `None` on 404.
- `search_shows` unwraps the `{score, show}` envelope and returns only the
  show payloads.
- `TVmazeCastMember` flattens the nested `character.name` into
  `character_name` for convenience.

---
[← AudioDBClient](audiodb.md) · [Home](../README.md) · [BlurayComClient →](bluray-com.md)
