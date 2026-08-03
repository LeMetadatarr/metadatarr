"""Declarative engine for metadatarr's resumable bulk scrapers.

Every scraper harvests one upstream catalogue into a JSONL dataset under
``~/.cache/metadatarr/scrapers`` (see :mod:`metadatarr.scrapers._checkpoint`).
They all share the same skeleton — resume from a cursor, fetch a page, map raw
records to flat rows, dedup by an id field, append, checkpoint, throttle, repeat
— which used to be copy-pasted into ~50 near-identical files.

The engine captures that skeleton once. A concrete scraper is a :class:`Source`
that answers two questions:

* :meth:`Source.initial_cursor` — where a fresh run starts.
* :meth:`Source.fetch` — given a cursor, return ``(rows, next_cursor)``; a
  ``next_cursor`` of ``None`` means the harvest is complete.

The cursor is any JSON-serialisable value (an ``int`` skip offset, a dict of
``{range_idx, skip}``, an opaque ``next`` URL — whatever the source needs), so
both trivial offset pagination and awkward partitioned crawls fit the same loop.

Most JSON REST catalogues need nothing more than :class:`PaginatedJSONSource`:
set ``base``/``results_key``/``page_size`` and implement :meth:`map_row`. HTML
catalogues use :class:`PaginatedHTMLSource`. Anything stranger overrides
:meth:`Source.fetch` directly and still gets resume/dedup/checkpoint for free.

Run one from the command line with :func:`run_cli`; the file's ``__main__``
block is a one-liner. ``python -m metadatarr.scrapers <name>`` dispatches by
registry name (see :func:`register` / :func:`get_source`).
"""
from __future__ import annotations

import argparse
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from metadatarr.scrapers._checkpoint import (
    Throttle,
    append_rows,
    count_rows,
    default_output_dir,
    load_checkpoint,
    load_existing_ids,
    save_checkpoint,
)

LOG = logging.getLogger("metadatarr.scrapers")

# A cursor is any JSON-serialisable position marker. None signals "done".
Cursor = Any
Row = Dict[str, Any]
Page = Tuple[List[Row], Cursor]


class Source(ABC):
    """Base class for a resumable bulk scraper.

    Subclasses set :attr:`name` and :attr:`id_field` and implement
    :meth:`fetch`. The engine (:meth:`run`) owns everything else: loading the
    saved cursor, deduplicating against already-written rows, appending,
    checkpointing after every page, throttling, and honouring ``limit``.
    """

    #: Dataset name — the JSONL and checkpoint files are named after it.
    name: str = ""
    #: Row key used to deduplicate across pages/restarts. Empty disables dedup.
    id_field: str = ""
    #: Default seconds between requests; overridable via ``--delay``.
    default_delay: float = 1.0

    def __init__(self, *, delay: Optional[float] = None) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must set a class-level `name`")
        self.throttle = Throttle(min_delay=self.default_delay if delay is None else delay)

    # -- optional CLI hooks -------------------------------------------------
    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Register scraper-specific CLI flags. Default: none.

        Override to add options (e.g. ``--enrich``); read them back in
        :meth:`configure`.
        """

    def configure(self, args: argparse.Namespace) -> None:
        """Apply parsed CLI args from :meth:`add_cli_arguments`. Default: no-op."""

    # -- to implement -------------------------------------------------------
    def initial_cursor(self) -> Cursor:
        """Cursor a fresh (checkpoint-less) run starts from. Default: ``0``."""
        return 0

    @abstractmethod
    def fetch(self, cursor: Cursor) -> Page:
        """Fetch one page at *cursor*.

        Return ``(rows, next_cursor)``. ``rows`` are already-mapped flat dicts.
        ``next_cursor`` is where the next page lives, or ``None`` when the
        harvest is complete. Implementations should call :meth:`Throttle.wait`
        (via ``self.throttle.wait()``) around the network hit, or let a
        :class:`PaginatedJSONSource`/:class:`PaginatedHTMLSource` do it.
        """
        raise NotImplementedError

    # -- engine loop --------------------------------------------------------
    def run(self, output_dir: Optional[Path] = None, *, limit: int = 0) -> int:
        """Harvest until exhausted (or ``limit`` new-or-existing rows reached).

        Returns the total row count in the dataset afterwards. Safe to
        interrupt and re-run: it resumes from the last checkpoint and skips
        rows whose :attr:`id_field` was already written.
        """
        output_dir = output_dir or default_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        ckpt = load_checkpoint(self.name, output_dir)
        cursor = ckpt.get("cursor", self.initial_cursor())
        seen = (load_existing_ids(self.name, self.id_field, output_dir)
                if self.id_field else set())
        # Exposed for fetch() overrides that need the full persisted id set
        # (e.g. computing a probe range over everything ever harvested), not
        # just what this process has produced. Updated in place as rows land.
        self._seen = seen
        total = count_rows(self.name, output_dir)
        LOG.info("[%s] resuming: cursor=%r, %d rows already collected",
                 self.name, cursor, total)

        while True:
            rows, next_cursor = self.fetch(cursor)

            if self.id_field:
                fresh = []
                for r in rows:
                    key = str(r.get(self.id_field))
                    if key in seen:
                        continue
                    seen.add(key)
                    fresh.append(r)
            else:
                fresh = list(rows)

            if fresh:
                total += append_rows(self.name, fresh, output_dir)
            # Checkpoint the *next* cursor so a restart doesn't re-fetch this page.
            save_checkpoint(self.name, {"cursor": next_cursor, "total": total},
                            output_dir)
            LOG.info("[%s] cursor=%r -> +%d rows (total=%d)",
                     self.name, cursor, len(fresh), total)

            if limit and total >= limit:
                LOG.info("[%s] limit %d reached", self.name, limit)
                break
            if next_cursor is None:
                LOG.info("[%s] complete — %d rows", self.name, total)
                break
            cursor = next_cursor

        return total


# ---------------------------------------------------------------------------
# HTTP mixin — one shared session policy for every networked source.
# ---------------------------------------------------------------------------

class _HttpMixin:
    """Lazy shared HTTP session with a sensible default header set.

    ``requests_session_factory`` lets a source swap in an
    ``unblock_requests`` Cloudflare session (or a test double) without
    changing the fetch code.
    """

    user_agent: str = "metadatarr-scraper/1.0 (+https://github.com/LeMetadatarr/metadatarr)"
    accept: str = "application/json"
    timeout: int = 30
    #: Network retries per request before giving up. Backoff is linear:
    #: ``backoff_base * attempt`` seconds.
    max_retries: int = 4
    backoff_base: float = 10.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._session = None

    def session(self):
        if self._session is None:
            import requests
            s = requests.Session()
            s.headers.update({"User-Agent": self.user_agent, "Accept": self.accept})
            self._session = s
        return self._session

    def _request(self, url: str, params: Optional[Dict[str, Any]]):
        import time

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            self.throttle.wait()  # type: ignore[attr-defined]
            try:
                r = self.session().get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                return r
            except Exception as exc:  # network/HTTP error — retry with backoff
                last_exc = exc
                if attempt < self.max_retries:
                    wait = self.backoff_base * attempt
                    LOG.warning("[%s] %s (attempt %d/%d) — retrying in %.0fs",
                                getattr(self, "name", "?"), exc, attempt,
                                self.max_retries, wait)
                    time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request(url, params).json()

    def get_text(self, url: str, params: Optional[Dict[str, Any]] = None) -> str:
        return self._request(url, params).text


# ---------------------------------------------------------------------------
# Declarative JSON pagination — the common case.
# ---------------------------------------------------------------------------

def deep_get(obj: Any, path: str) -> Any:
    """Follow a dotted key path into nested dicts; return None on any miss."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


class PaginatedJSONSource(_HttpMixin, Source):
    """Offset-paginated JSON REST catalogue.

    Set :attr:`base`, :attr:`results_key` (dotted path to the record list),
    and :attr:`page_size`; implement :meth:`map_row`. The engine walks
    ``skip`` in ``page_size`` steps and stops when a short page arrives.
    Override :attr:`skip_param`/:attr:`limit_param`/:attr:`extra_params` for
    APIs that name things differently.
    """

    base: str = ""
    results_key: str = "results"
    page_size: int = 100
    skip_param: str = "skip"
    limit_param: str = "limit"
    extra_params: Dict[str, Any] = {}

    def initial_cursor(self) -> int:
        return 0

    def map_row(self, record: Dict[str, Any]) -> Optional[Row]:
        """Map one upstream record to a flat row. Return None to drop it."""
        return record

    def fetch(self, cursor: int) -> Page:
        skip = int(cursor or 0)
        params = dict(self.extra_params)
        params[self.limit_param] = self.page_size
        params[self.skip_param] = skip
        data = self.get_json(self.base, params)
        records = deep_get(data, self.results_key) or []
        rows = []
        for rec in records:
            row = self.map_row(rec)
            if row is not None:
                rows.append(row)
        next_cursor = None if len(records) < self.page_size else skip + self.page_size
        return rows, next_cursor


class PartitionedJSONSource(PaginatedJSONSource):
    """Offset pagination repeated across a list of query *partitions*.

    Many catalogues cap how deep a single offset walk can go, so they are
    harvested as ``partitions × offset`` — Open Library iterates subject seeds,
    openFDA iterates date-range search strings, etc. Implement
    :meth:`partitions` to return one params-dict per seed; the engine walks
    each seed's offsets and moves to the next when a seed runs short. Global
    dedup by :attr:`id_field` (done in :meth:`Source.run`) removes overlap
    between seeds.

    The cursor is ``{"part": <index>, "skip": <offset>}``.
    """

    def partitions(self) -> List[Dict[str, Any]]:
        """Return one params-dict per partition (seed). Must be stable across
        runs so a saved ``part`` index still points at the same seed."""
        raise NotImplementedError

    def initial_cursor(self) -> Dict[str, int]:
        return {"part": 0, "skip": 0}

    def fetch(self, cursor: Dict[str, int]) -> Page:
        parts = self.partitions()
        part = int(cursor.get("part", 0))
        skip = int(cursor.get("skip", 0))
        if part >= len(parts):
            return [], None

        params = dict(self.extra_params)
        params.update(parts[part])
        params[self.limit_param] = self.page_size
        params[self.skip_param] = skip
        data = self.get_json(self.base, params)
        records = deep_get(data, self.results_key) or []
        rows = []
        for rec in records:
            row = self.map_row(rec)
            if row is not None:
                rows.append(row)

        if len(records) < self.page_size:
            # Seed exhausted — advance to the next, or finish.
            next_part = part + 1
            next_cursor = ({"part": next_part, "skip": 0}
                           if next_part < len(parts) else None)
        else:
            next_cursor = {"part": part, "skip": skip + self.page_size}
        return rows, next_cursor


class PaginatedHTMLSource(_HttpMixin, Source):
    """Page-numbered HTML catalogue parsed with BeautifulSoup.

    Set :attr:`url_template` (a ``str.format`` template taking ``page``) and
    implement :meth:`parse_page`, which receives the ``BeautifulSoup`` and
    returns this page's rows. Return an empty list to signal the last page.
    """

    accept: str = "text/html,application/xhtml+xml"
    url_template: str = ""
    first_page: int = 1

    def initial_cursor(self) -> int:
        return self.first_page

    def parse_page(self, soup: Any, page: int) -> List[Row]:
        raise NotImplementedError

    def fetch(self, cursor: int) -> Page:
        from bs4 import BeautifulSoup

        page = int(cursor)
        html = self.get_text(self.url_template.format(page=page))
        soup = BeautifulSoup(html, "html.parser")
        rows = self.parse_page(soup, page)
        next_cursor = None if not rows else page + 1
        return rows, next_cursor


# ---------------------------------------------------------------------------
# Registry + CLI
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, type] = {}


def register(source_cls: type) -> type:
    """Register a Source subclass by its ``name`` for CLI dispatch. Usable as
    a decorator."""
    name = getattr(source_cls, "name", "")
    if not name:
        raise ValueError(f"{source_cls.__name__} has no `name` to register")
    _REGISTRY[name] = source_cls
    return source_cls


def get_source(name: str) -> type:
    if name not in _REGISTRY:
        raise KeyError(f"unknown scraper: {name!r}")
    return _REGISTRY[name]


def all_sources() -> Dict[str, type]:
    return dict(_REGISTRY)


def run_cli(source_cls: type, argv: Optional[List[str]] = None) -> int:
    """Standard ``argparse`` entry point for a single scraper module.

    Gives every scraper the same ``--output/--delay/--limit`` flags so the
    ``__main__`` block of a scraper file is just ``run_cli(MySource)``.
    """
    ap = argparse.ArgumentParser(description=f"{source_cls.name} scraper")
    ap.add_argument("--output", default=str(default_output_dir()),
                    help="output directory for JSONL + checkpoint")
    ap.add_argument("--delay", type=float, default=None,
                    help="seconds between requests (default: source-specific)")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after the dataset reaches this many rows (0 = all)")
    ap.add_argument("-v", "--verbose", action="store_true")
    source_cls.add_cli_arguments(ap)
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    source = source_cls(delay=args.delay)
    source.configure(args)
    total = source.run(Path(args.output), limit=args.limit)
    LOG.info("[%s] finished with %d rows", source_cls.name, total)
    return 0
