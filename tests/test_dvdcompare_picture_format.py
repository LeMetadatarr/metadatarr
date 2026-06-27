"""DVDCompare provider derives a canonical PictureFormat from version text."""
from __future__ import annotations

import pytest

from mediavocab import MediaType, PictureFormat
from mediavocab.models.signals import Signals

from metadatarr.models import DVDCompareEdition
from metadatarr.resolve.providers.dvdcompare import (
    _infer_picture_format,
    _match_to_provider,
)


@pytest.mark.parametrize(
    "version, disc_format, expected",
    [
        ("Colorized Edition", None, PictureFormat.COLORIZED),
        ("Restored B&W", None, PictureFormat.BLACK_AND_WHITE),
        ("Black and White Version", None, PictureFormat.BLACK_AND_WHITE),
        ("3D Blu-ray", None, PictureFormat.THREE_D),
        ("IMAX Enhanced", None, PictureFormat.IMAX),
        (None, "4K UHD Blu-ray", PictureFormat.FOUR_K),
        ("Director's Cut", "Blu-ray", None),     # no picture-format cue
        (None, None, None),
    ],
)
def test_infer_picture_format(version, disc_format, expected):
    assert _infer_picture_format(version, disc_format) is expected


def test_match_emits_picture_format():
    edition = DVDCompareEdition(
        dvdcompare_id="16880",
        title="Metropolis (1927)",
        version="Restored Colorized Edition",
        disc_format="Blu-ray",
        imdb_id="tt0017136",
    )
    match = _match_to_provider(Signals(title="Metropolis", medium=MediaType.MOVIE),
                               edition)
    assert match.signals.picture_format is PictureFormat.COLORIZED
    # source_format stays the distribution/container, not the picture format
    assert match.signals.source_format == "Blu-ray"
