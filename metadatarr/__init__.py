"""metadatarr — Pydantic-powered media metadata clients + cross-source resolver."""

from .version import __version__

from .client import (
    ArrMetadataClient,
    AnnasArchiveClient,
    BookInfoClient,
    OpenLibraryClient,
    AudioDBClient,
    TVmazeClient,
)
from .models import (
    SonarrSeries,
    RadarrMovie,
    LidarrArtist,
    AnnasArchiveBook,
    BookInfoSearchHit,
    BookInfoWork,
    BookInfoBook,
    BookInfoAuthor,
    OpenLibrarySearchHit,
    OpenLibraryWork,
    OpenLibraryEdition,
    OpenLibraryAuthor,
    CutRuntime,
    DVDCompareRelease,
    DVDCompareEdition,
    Stream,
)
from . import resolve  # noqa: F401  — populates the provider registry

__all__ = [
    "__version__",
    "resolve",
    "ArrMetadataClient",
    "AnnasArchiveClient",
    "BookInfoClient",
    "OpenLibraryClient",
    "AudioDBClient",
    "TVmazeClient",
    "SonarrSeries",
    "RadarrMovie",
    "LidarrArtist",
    "AnnasArchiveBook",
    "BookInfoSearchHit",
    "BookInfoWork",
    "BookInfoBook",
    "BookInfoAuthor",
    "OpenLibrarySearchHit",
    "OpenLibraryWork",
    "OpenLibraryEdition",
    "OpenLibraryAuthor",
    "CutRuntime",
    "DVDCompareRelease",
    "DVDCompareEdition",
    "Stream",
]
