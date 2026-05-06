"""Built-in metadata providers.

Importing this subpackage triggers self-registration of every provider
whose hard dependencies are present. Providers with optional dependencies
(``pymetal``, ``py_bandcamp``, ``nuvem_de_som``, ``tutubo``) self-disable
via :meth:`is_available` rather than failing the import — so the ``metadatarr``
package always imports cleanly regardless of which extras are installed.

Use :func:`metadatarr.resolve.active_providers` to discover what's currently
usable; :func:`all_providers` returns the full registry.

Optional extras (declare in your environment with ``pip install
metadatarr[<extra>]``):

==================  ============================  ============================
extra               pulls in                       enables provider
==================  ============================  ============================
``metal_archives``  ``pymetal>=0.6``               ``metal_archives``
``bandcamp``        ``py_bandcamp``                ``bandcamp``
``soundcloud``      ``nuvem_de_som``               ``soundcloud``
``youtube``         ``tutubo``                     ``youtube`` + ``youtube_music``
``all``             all of the above
==================  ============================  ============================

Always-on providers (no optional deps, no API key):

- ``pyfanedit``   — fanedit.org / IFDB variant lookup (fanedits, director's cuts)
- ``bluray_com``  — blu-ray.com HTML scraper (technical specs, regional editions)
- ``dvdcompare``  — dvdcompare.net HTML scraper (version/cut metadata)
- ``discogs``     — Discogs public API (labels, VHS/LaserDisc, catalogue numbers)

The ``youtube`` extra enables both providers — they share a dependency.
They serve different roles: ``youtube`` covers original-to-YouTube content
(channels, vlogs, podcasts) and never claims music; ``youtube_music``
covers music using YT Music's proper artist/album ``browseId`` entity
records.

Each provider module's import is itself wrapped in ``try/except
ImportError`` here as a belt-and-braces guard: the provider classes
catch missing optional deps internally, but if a future provider grew an
unconditional top-level import we still don't want it to take down the
whole registry.
"""
from __future__ import annotations

import logging as _logging

_LOG = _logging.getLogger("metadatarr.resolve.providers")

# Always-available providers — self-register on import.
from metadatarr.resolve.providers import musicbrainz       # noqa: F401, E402
from metadatarr.resolve.providers import wikidata          # noqa: F401, E402
from metadatarr.resolve.providers import servarr_proxy     # noqa: F401, E402
from metadatarr.resolve.providers import audiodb           # noqa: F401, E402
from metadatarr.resolve.providers import tvmaze            # noqa: F401, E402
from metadatarr.resolve.providers import pyfanedit         # noqa: F401, E402
# Generic external-API providers (lifted from media-archivist)
from metadatarr.resolve.providers import anilist           # noqa: F401, E402
from metadatarr.resolve.providers import jikan             # noqa: F401, E402
from metadatarr.resolve.providers import google_books      # noqa: F401, E402
from metadatarr.resolve.providers import librivox          # noqa: F401, E402
from metadatarr.resolve.providers import podcast_index     # noqa: F401, E402
from metadatarr.resolve.providers import openlibrary       # noqa: F401, E402
from metadatarr.resolve.providers import annas_archive     # noqa: F401, E402
from metadatarr.resolve.providers import arr               # noqa: F401, E402


def _try_register(module_name: str) -> None:
    try:
        __import__(f"metadatarr.resolve.providers.{module_name}")
    except ImportError as exc:  # pragma: no cover — defensive only
        _LOG.debug("%s provider unavailable: %s", module_name, exc)


# Optional providers — each one self-disables via is_available() if its
# upstream dep is missing, but the import wrapper here protects against a
# stray top-level import failure too.
for _opt in ("metal_archives", "bandcamp", "soundcloud", "youtube", "youtube_music",
              "bluray_com", "dvdcompare", "discogs"):
    _try_register(_opt)
