"""Dispatch a registered scraper by name.

    python -m metadatarr.scrapers <name> [--output DIR] [--delay S] [--limit N]
    python -m metadatarr.scrapers --list

Each scraper module registers its :class:`~metadatarr.scrapers.engine.Source`
on import; importing this package's modules populates the registry.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys

import metadatarr.scrapers as _pkg
from metadatarr.scrapers.engine import all_sources, get_source, run_cli


def _load_all() -> None:
    for mod in pkgutil.iter_modules(_pkg.__path__):
        if mod.name.startswith("_") or mod.name in ("engine",):
            continue
        importlib.import_module(f"metadatarr.scrapers.{mod.name}")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _load_all()

    if not argv or argv[0] in ("--list", "-l", "list"):
        for name in sorted(all_sources()):
            print(name)
        return 0

    name, rest = argv[0], argv[1:]
    try:
        source_cls = get_source(name)
    except KeyError:
        print(f"unknown scraper: {name!r}. Use --list to see available ones.",
              file=sys.stderr)
        return 2
    return run_cli(source_cls, rest)


if __name__ == "__main__":
    raise SystemExit(main())
