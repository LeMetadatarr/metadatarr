"""Built-in metadata providers.

Importing this subpackage triggers self-registration of every provider
in this directory. Each module calls :func:`metadatarr.resolve.register`
at import time, so the registry is built by side-effect.

Auto-discovery: every ``*.py`` sibling (except those starting with ``_``)
is imported via :func:`pkgutil.iter_modules`. Adding a new provider is a
single-file drop — no edits to this file required. Providers with
optional runtime deps (``pymetal``, ``py_bandcamp``, ``nuvem_de_som``,
``tutubo``) catch :class:`ImportError` internally and self-disable via
:meth:`MetadataProvider.is_available`; if a module can't even import,
this loop logs at DEBUG and continues — so a single broken provider
never takes down the registry.

Use :func:`metadatarr.resolve.active_providers` to discover what's
currently usable; :func:`all_providers` returns the full registry.
"""
from __future__ import annotations

import importlib as _importlib
import logging as _logging
import pkgutil as _pkgutil

_LOG = _logging.getLogger("metadatarr.resolve.providers")


def _autoload() -> None:
    for info in _pkgutil.iter_modules(__path__):
        if info.ispkg or info.name.startswith("_"):
            continue
        try:
            _importlib.import_module(f"{__name__}.{info.name}")
        except ImportError as exc:
            _LOG.debug("%s provider unavailable: %s", info.name, exc)


_autoload()
