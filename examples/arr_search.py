"""Search the Servarr metadata proxies for TV, movie, and artist."""
from metadatarr import ArrMetadataClient


def main() -> None:
    client = ArrMetadataClient()

    print("--- Sonarr / Skyhook: 'The Boys' ---")
    for series in client.search_series("The Boys")[:3]:
        print(f"  {series.title}  tvdb={series.tvdb_id}")

    print("\n--- Radarr: 'Inception' ---")
    for movie in client.search_movie("Inception")[:3]:
        print(f"  {movie.title} ({movie.year})  tmdb={movie.tmdb_id}")

    print("\n--- Lidarr: 'Daft Punk' ---")
    for artist in client.search_artist("Daft Punk")[:3]:
        print(f"  {artist.name}  mbid={artist.id}")


if __name__ == "__main__":
    main()
