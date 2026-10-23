"""Provider plugins from installed distributions.

A distribution declares an entry point in the ``metadatarr.providers`` group.
The entry point names a module or a zero-argument callable. A module is
imported; a callable is called. Either is expected to call
:func:`metadatarr.resolve.register` for each provider it ships. Plugins load
once, after the built-in providers. A plugin that fails is logged and skipped.

Set ``METADATARR_DISABLE_PLUGINS=1`` to skip plugin loading.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from importlib import metadata
from typing import List, Optional

from metadatarr.resolve import base

GROUP = "metadatarr.providers"
DISABLE_ENV = "METADATARR_DISABLE_PLUGINS"

_LOG = logging.getLogger("metadatarr.resolve.providers")


@dataclass(frozen=True)
class PluginStatus:
    name: str
    distribution: Optional[str] = None
    version: Optional[str] = None
    error: Optional[str] = None


_STATUS: List[PluginStatus] = []
_LOADED = False


def plugins_disabled() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def load_plugins(force: bool = False) -> List[PluginStatus]:
    """Load entry-point plugins once and return their status list."""
    global _LOADED
    if _LOADED and not force:
        return list(_STATUS)
    _LOADED = True
    _STATUS.clear()
    if plugins_disabled():
        return []
    try:
        found = metadata.entry_points()
        found = found.select(group=GROUP) if hasattr(found, "select") else found.get(GROUP, [])
        eps = sorted(found, key=lambda e: e.name)
    except Exception as exc:
        _LOG.error("could not enumerate %s entry points: %s", GROUP, exc)
        return []
    for ep in eps:
        dist = getattr(ep, "dist", None)
        dist_name = dist.metadata["Name"] if dist is not None else None
        dist_version = dist.version if dist is not None else None
        error = None
        before = dict(base._REGISTRY)
        try:
            target = ep.load()
            if callable(target) and not isinstance(target, type(os)):
                target()
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            _LOG.error("provider plugin %r (%s) failed to load: %s", ep.name, dist_name, error)
        problem = _settle_registry(ep.name, before, failed=error is not None)
        if error is None and problem is not None:
            error = problem
            _LOG.error("provider plugin %r (%s): %s", ep.name, dist_name, error)
        _STATUS.append(PluginStatus(ep.name, dist_name, dist_version, error))
    return list(_STATUS)


def _settle_registry(plugin: str, before: dict, failed: bool) -> Optional[str]:
    """Undo a failed plugin's registrations, refuse overrides of existing names,
    drop objects that are not providers and restore removed built-ins.

    Returns a description of what went wrong for a plugin that did not fail
    outright but removed built-ins, refused overrides, registered an invalid
    object or registered nothing, else ``None``.
    """
    registry = base._REGISTRY
    added = refused = removed = invalid = 0
    for name, provider in list(registry.items()):
        if isinstance(provider, base.MetadataProvider):
            continue
        invalid += 1
        _LOG.warning("provider plugin %r registered %s under %r, which is not a "
                     "MetadataProvider; dropping it", plugin, type(provider).__name__, name)
        if name in before:
            registry[name] = before[name]
        else:
            del registry[name]
    for name, previous in before.items():
        if name not in registry:
            removed += 1
            _LOG.warning("provider plugin %r removed provider %r; restoring it", plugin, name)
            registry[name] = previous
    for name, provider in list(registry.items()):
        previous = before.get(name)
        if previous is provider:
            continue
        if previous is None:
            if failed:
                del registry[name]
            else:
                added += 1
            continue
        refused += 1
        _LOG.warning(
            "provider plugin %r tried to replace provider %r (%s) with %s; keeping %s",
            plugin, name, type(previous).__name__, type(provider).__name__,
            type(previous).__name__)
        registry[name] = previous
    if failed:
        return None
    problems = []
    if removed:
        problems.append(f"removed {removed} built-in provider(s); restored")
    if refused:
        problems.append(f"refused to replace {refused} existing provider(s)")
    if invalid:
        problems.append(f"registered {invalid} object(s) that are not MetadataProvider; dropped")
    if not added and not problems:
        problems.append("registered no providers")
    return "; ".join(problems) or None


def loaded_plugins() -> List[PluginStatus]:
    """Status of every plugin attempted so far (empty when disabled)."""
    return list(_STATUS)
