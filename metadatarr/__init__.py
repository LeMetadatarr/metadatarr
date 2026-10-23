"""metadatarr — Pydantic-powered media metadata clients + cross-source resolver."""

from .version import __version__

from .client import (
    ArrMetadataClient,
    AnnasArchiveClient,
    BookInfoClient,
    OpenLibraryClient,
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
)
from . import resolve  # noqa: F401  — submodule; populates the provider registry
# Headline resolver entry points, re-exported for convenience. The `resolve`
# *function* is reached as `metadatarr.resolve.resolve` (the line above keeps
# `metadatarr.resolve` bound to the submodule); these are the other top-level
# verbs callers reach for, plus the input/output types.
from .resolve import (  # noqa: F401
    Signals,
    MediaType,
    ResolveResult,
    ProviderMatch,
    candidates,
    consolidate,
    enrich,
)

__all__ = [
    "__version__",
    "resolve",
    "Signals",
    "MediaType",
    "ResolveResult",
    "ProviderMatch",
    "candidates",
    "consolidate",
    "enrich",
    "ArrMetadataClient",
    "AnnasArchiveClient",
    "BookInfoClient",
    "OpenLibraryClient",
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
]
