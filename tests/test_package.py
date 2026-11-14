"""Smoke tests for top-level package exports."""
import metadatarr


def test_version_is_set():
    assert isinstance(metadatarr.__version__, str)
    assert metadatarr.__version__.count(".") == 2


def test_clients_exported():
    for name in (
        "ArrMetadataClient",
        "AnnasArchiveClient",
        "BookInfoClient",
        "OpenLibraryClient",
    ):
        assert hasattr(metadatarr, name), f"missing export: {name}"


def test_resolve_subpackage_loaded():
    assert hasattr(metadatarr, "resolve")
    assert metadatarr.resolve.MetadataProvider is not None
