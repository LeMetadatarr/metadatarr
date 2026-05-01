"""AudioDB artist + album lookup."""
from metadatarr import AudioDBClient


def main() -> None:
    client = AudioDBClient()

    print("--- AudioDB: artist 'Daft Punk' ---")
    artists = client.search_artist("Daft Punk")
    if not artists:
        print("  no results")
        return
    artist = artists[0]
    print(f"  {artist.name}  id={artist.id}  mbid={artist.musicbrainz_id}")
    print(f"  formed={artist.formed_year}  country={artist.country}")

    print("\n--- AudioDB: discography ---")
    for album in client.discography("Daft Punk")[:5]:
        print(f"  {album.year}  {album.name}")


if __name__ == "__main__":
    main()
