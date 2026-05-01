"""Look up the same book through three independent backends."""
from metadatarr import (
    AnnasArchiveClient,
    BookInfoClient,
    OpenLibraryClient,
)


def main() -> None:
    title = "The Hobbit"

    print(f"--- OpenLibrary: '{title}' ---")
    ol = OpenLibraryClient()
    for hit in ol.search(title, limit=3):
        print(f"  {hit.title}  work_key={hit.work_key}")

    print(f"\n--- BookInfo (Goodreads): '{title}' ---")
    bi = BookInfoClient.goodreads()
    for hit in bi.search(title)[:3]:
        print(f"  book_id={hit.book_id}  work_id={hit.work_id}")

    print(f"\n--- Anna's Archive: '{title}' ---")
    aa = AnnasArchiveClient()
    for book in aa.search(title)[:3]:
        print(f"  {book.title}  by {book.author}  [{book.formats}]  md5={book.md5}")


if __name__ == "__main__":
    main()
