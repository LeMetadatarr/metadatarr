# SPDX-License-Identifier: Apache-2.0
"""Catalogue sources and the dispatcher that asks them.

A catalogue source answers questions keyed by an identifier: the details of
an item with its children one level down (``lookup``), the people credited on
it (``credits``), a person with their filmography (``person``), the videos that
belong to an item (``extras``) and the other versions of a work that are not
the studio's, such as fan edits (``variants``). Each source
declares, per question, which item kinds and identifier schemes it can answer;
that declaration is what ``GET /providers`` reports as ``capabilities`` and
what the dispatcher routes on.

A source carries the name of the resolver provider it belongs to and is
available exactly when that provider is (TMDB, for instance, needs
``TMDB_API_KEY``). The dispatcher asks the capable sources in priority order:
the first one that knows the identifier answers; a source may rank itself
differently for one question (TMDB lists more extras than the Servarr proxy's
single trailer, so it is asked first for those). A source that fails or runs
past its timeout is recorded in the answer's ``errors`` and the next one is
asked, so one failing catalogue never fails a request.

Answers are kept in a bounded in-memory cache for a fixed time; ``refresh``
asks the catalogues again and replaces the cached answer. "Not found", a
failure and an answer given while a better source failed are never kept.

Settings (environment): ``METADATARR_CATALOG_TIMEOUT`` seconds per source
(default 10), ``METADATARR_CATALOG_CACHE_TTL`` seconds (default 3600) and
``METADATARR_CATALOG_CACHE_SIZE`` answers (default 1000; 0 disables the cache).
"""
from __future__ import annotations

import contextvars
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, FrozenSet, List, Optional, Tuple

from metadatarr.resolve._errors import ProviderError
from metadatarr.transport import bypass_cache

LOG = logging.getLogger("metadatarr.catalog")

METHODS = ("lookup", "credits", "person", "extras", "variants")

#: Item kinds the catalogue routes know.
KINDS = ("movie", "collection", "series", "season", "episode", "artist", "album", "track",
         "author", "book", "show", "audiobook", "chapter")

#: The kind of an item's children, one level down.
CHILD_KIND = {"series": "season", "season": "episode", "show": "episode", "artist": "album",
              "album": "track", "author": "book", "audiobook": "chapter", "collection": "movie"}

#: The kind an identifier names when the caller does not say.
DEFAULT_KIND = {"tmdb": "movie", "imdb": "movie", "tvdb": "series", "tvmaze": "series",
                "musicbrainz": "album", "anilist": "series", "mal": "series", "isbn": "book",
                "librivox": "audiobook", "apple_podcasts": "show"}

#: Schemes whose ids are positive integers, with the largest id each catalogue can hold.
NUMERIC_SCHEMES = {"tmdb": 2**31 - 1, "tvdb": 2**31 - 1, "tvmaze": 2**31 - 1, "anilist": 2**31 - 1,
                   "mal": 2**31 - 1, "librivox": 2**31 - 1, "apple_podcasts": 2**63 - 1, "discogs": 2**31 - 1}
#: Kinds named ``<series id>/<season number>`` in these schemes.
COMPOSITE_KINDS = {"season"}

#: A MusicBrainz id: a UUID, ASCII hex only.
_MBID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

#: ExternalIds fields holding a MusicBrainz id.
_MBID_FIELDS = ("musicbrainz_recording", "musicbrainz_release", "musicbrainz_release_group", "musicbrainz_work",
                "musicbrainz_artist", "musicbrainz_label")
_ISBN = re.compile(r"[0-9]{9}[0-9Xx]|[0-9]{13}")
#: An Open Library id: ``OL`` digits and the record type (author, edition, work). Stricter than the
#: catalogue source (upper case, at most 12 digits) because the resolve route does not validate olid.
_OLID = re.compile(r"OL[0-9]{1,12}[AMW]")
#: A DVDCompare film id.
_DVDCOMPARE_ID = re.compile(r"[0-9]{1,12}")

DEFAULT_TIMEOUT = 10.0
DEFAULT_CACHE_TTL = 3600
DEFAULT_CACHE_SIZE = 1000
MAX_VALUE_LENGTH = 200


class InvalidId(ValueError):
    """An identifier that cannot name anything in its scheme (not a number, out of range)."""


class NotSupported(Exception):
    """No available source can answer this question. ``provider`` names the
    source the caller asked for, when it asked for one."""

    def __init__(self, message: str, provider: Optional[str] = None) -> None:
        super().__init__(message)
        self.provider = provider


def default_kind(scheme: str, value: str) -> Optional[str]:
    if scheme == "openlibrary":
        return "author" if value.upper().endswith("A") else "book"
    return DEFAULT_KIND.get(scheme)


class CatalogSource:
    """One catalogue. Subclasses set the capability tables and override the
    methods they can answer; each returns ``None`` when the catalogue does not
    know the identifier and raises on any failure."""

    name: ClassVar[str] = ""
    priority: ClassVar[int] = 50
    #: kind -> schemes a lookup takes
    lookup_kinds: ClassVar[Dict[str, Tuple[str, ...]]] = {}
    #: kinds whose lookup carries the children one level down
    children_kinds: ClassVar[FrozenSet[str]] = frozenset()
    #: kind -> schemes a credits question takes
    credits_kinds: ClassVar[Dict[str, Tuple[str, ...]]] = {}
    #: schemes a person question takes
    person_schemes: ClassVar[Tuple[str, ...]] = ()
    #: kind -> schemes an extras question takes
    extras_kinds: ClassVar[Dict[str, Tuple[str, ...]]] = {}
    #: kind -> schemes a variants question takes
    variants_kinds: ClassVar[Dict[str, Tuple[str, ...]]] = {}
    #: method -> priority, where the source ranks differently for that question
    method_priority: ClassVar[Dict[str, int]] = {}
    #: when the caller names no kind, the source is given ``kind=None`` and
    #: answers with the kind the catalogue records (AniList: movie or series)
    infers_kind: ClassVar[bool] = False

    def available(self) -> bool:
        from metadatarr.resolve.base import _is_available, all_providers

        provider = all_providers().get(self.name)
        return True if provider is None else _is_available(provider)

    def capabilities(self) -> Dict[str, Any]:
        return {
            "lookup": {k: list(s) for k, s in sorted(self.lookup_kinds.items())},
            "children": sorted(self.children_kinds),
            "credits": {k: list(s) for k, s in sorted(self.credits_kinds.items())},
            "person": list(self.person_schemes),
            "extras": {k: list(s) for k, s in sorted(self.extras_kinds.items())},
            "variants": {k: list(s) for k, s in sorted(self.variants_kinds.items())},
        }

    def can(self, method: str, scheme: str, kind: Optional[str]) -> bool:
        if method == "person":
            return scheme in self.person_schemes
        table = {"lookup": self.lookup_kinds, "credits": self.credits_kinds, "extras": self.extras_kinds,
                 "variants": self.variants_kinds}[method]
        return scheme in table.get(kind or "", ())

    def rank(self, method: str) -> int:
        return self.method_priority.get(method, self.priority)

    def lookup(self, scheme: str, value: str, kind: str, *, children: bool, timeout: float):
        raise NotImplementedError

    def credits(self, scheme: str, value: str, kind: str, *, timeout: float):
        raise NotImplementedError

    def person(self, scheme: str, value: str, *, timeout: float):
        raise NotImplementedError

    def extras(self, scheme: str, value: str, kind: str, *, timeout: float):
        """A list of :class:`~metadatarr.catalog.shapes.Extra`, empty when the
        item has none; ``None`` when the catalogue does not know the item."""
        raise NotImplementedError

    def variants(self, scheme: str, value: str, kind: str, *, title: str, year: Optional[int], timeout: float):
        """A list of :class:`~metadatarr.catalog.shapes.Item` with ``extra.variant``
        for the work named ``title``, empty when the catalogue lists none."""
        raise NotImplementedError


_SOURCES: Dict[str, CatalogSource] = {}


def register_source(source: CatalogSource) -> CatalogSource:
    if not source.name:
        raise ValueError("a catalogue source must declare a `name`")
    _SOURCES[source.name] = source
    return source


def all_sources() -> Dict[str, CatalogSource]:
    return dict(_SOURCES)


def capabilities_of(provider_name: str) -> Dict[str, Any]:
    """The capability table of a provider; empty tables when it has no catalogue source."""
    source = _SOURCES.get(provider_name)
    if source is None:
        return {"lookup": {}, "children": [], "credits": {}, "person": [], "extras": {}, "variants": {}}
    return source.capabilities()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class TTLCache:
    """At most ``max_entries`` answers, each kept ``ttl`` seconds; the oldest go first."""

    def __init__(self, ttl: float, max_entries: int, clock=time.monotonic) -> None:
        self.ttl, self.max_entries, self._clock = ttl, max_entries, clock
        self._data: "OrderedDict[Any, Tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key) -> Tuple[bool, Any]:
        with self._lock:
            hit = self._data.get(key)
            if hit is not None and hit[0] > self._clock():
                return True, hit[1]
            self._data.pop(key, None)
            return False, None

    def put(self, key, value) -> None:
        if self.max_entries <= 0 or self.ttl <= 0:
            return
        with self._lock:
            self._data.pop(key, None)
            while len(self._data) >= self.max_entries:
                self._data.popitem(last=False)
            self._data[key] = (self._clock() + self.ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


def _env_number(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        LOG.warning("invalid %s=%r, using %s", name, raw, default)
        return default


_CACHE: Optional[TTLCache] = None
_CACHE_LOCK = threading.Lock()


def cache() -> TTLCache:
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is None:
            _CACHE = TTLCache(_env_number("METADATARR_CATALOG_CACHE_TTL", DEFAULT_CACHE_TTL),
                              int(_env_number("METADATARR_CATALOG_CACHE_SIZE", DEFAULT_CACHE_SIZE)))
        return _CACHE


def reset_cache() -> None:
    """Drop the cache; the next answer builds a new one from the environment."""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None


def timeout() -> float:
    return max(0.1, _env_number("METADATARR_CATALOG_TIMEOUT", DEFAULT_TIMEOUT))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

@dataclass
class Answer:
    """What the sources said: ``value`` is ``None`` when none of them knew the
    identifier. ``providers`` lists the source whose answer this is, ``asked``
    every source that was asked, ``errors`` every source that failed."""

    value: Any
    providers: List[str] = field(default_factory=list)
    asked: List[str] = field(default_factory=list)
    errors: List[ProviderError] = field(default_factory=list)
    truncated: bool = False
    #: ``{"source": "live"}`` or the dataset an offline row came from; ``None``
    #: while the offline layer is off.
    origin: Optional[Dict[str, Any]] = None


_TRUNCATED: contextvars.ContextVar = contextvars.ContextVar("metadatarr_catalog_truncated", default=None)


def mark_truncated() -> None:
    """Called by a source whose answer stops short of everything the catalogue
    has (a page limit, the time budget); the answer reports ``truncated``."""
    holder = _TRUNCATED.get()
    if holder is not None:
        holder[0] = True


def report_partial_failure(error: BaseException) -> None:
    """Called by a source that answers with what it read before a later request
    failed: the answer is truncated, the failure is listed under its errors,
    and so the answer is neither cached nor sent as cacheable."""
    mark_truncated()
    failures = _FAILURES.get()
    if failures is not None:
        failures.append(error)


_FAILURES: contextvars.ContextVar = contextvars.ContextVar("metadatarr_catalog_failures", default=None)


_SECRET_PARAM = re.compile(r"((?:api_?key|apikey|token|access_token|key)=)[^&\s'\"]+", re.IGNORECASE)


def _redact(message: str) -> str:
    """``message`` with credential query parameters masked; a request URL in an
    exception text must not hand a provider key to API clients."""
    return _SECRET_PARAM.sub(r"\1***", message)


def _call_with_timeout(fn, seconds: float):
    """``fn()`` in a worker thread, waiting at most ``seconds``. A call that
    overruns raises :class:`TimeoutError` here; its thread ends when its own
    request timeout fires."""
    box: Dict[str, Any] = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller
            box["error"] = e

    ctx = contextvars.copy_context()
    worker = threading.Thread(target=ctx.run, args=(run,), daemon=True, name="catalog-source")
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise TimeoutError(f"no answer within {seconds:g}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def check_request(method: str, scheme: str, value: str, kind: Optional[str]) -> Tuple[str, str, Optional[str]]:
    """Normalised ``(scheme, value, kind)``; :class:`ValueError` for a malformed
    question, :class:`InvalidId` for an id its scheme cannot hold."""
    scheme = (scheme or "").strip().lower()
    value = (value or "").strip()
    if not scheme:
        raise ValueError("scheme is required")
    if not value:
        raise ValueError("value is required")
    if len(value) > MAX_VALUE_LENGTH:
        raise ValueError(f"value is longer than {MAX_VALUE_LENGTH} characters")
    if method != "person":
        kind = (kind or "").strip().lower() or default_kind(scheme, value)
        if kind is None:
            raise ValueError(f"kind is required for scheme {scheme!r}")
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}; one of {', '.join(KINDS)}")
    if scheme == "imdb" and not re.fullmatch(("nm" if method == "person" else "tt") + "[0-9]{7,10}", value):
        raise InvalidId(f"{value!r} is not a valid {scheme} id")
    if scheme == "musicbrainz" and not _MBID.fullmatch(value):
        raise InvalidId(f"{value!r} is not a valid {scheme} id")
    if scheme in NUMERIC_SCHEMES:
        composite = method != "person" and kind in COMPOSITE_KINDS and scheme in ("tmdb", "tvdb")
        head, _, season = value.partition("/") if composite else (value, "", "")
        valid = head.isascii() and head.isdigit() and 0 < int(head) <= NUMERIC_SCHEMES[scheme]
        if composite:
            valid = valid and season.isascii() and season.isdigit()
        if not valid:
            raise InvalidId(f"{value!r} is not a valid {scheme} id")
    return scheme, value, None if method == "person" else kind


def check_external_ids(ids: Any) -> None:
    """:class:`InvalidId` when a musicbrainz, isbn, olid or dvdcompare field of ``ids``
    (an ExternalIds) is set to something its scheme cannot hold. An empty field is unset."""
    checks = [(name, _MBID, "musicbrainz") for name in _MBID_FIELDS]
    checks += [("olid", _OLID, "openlibrary"), ("dvdcompare_id", _DVDCOMPARE_ID, "dvdcompare")]
    for name, pattern, scheme in checks:
        value = getattr(ids, name, None)
        if value and not pattern.fullmatch(value):
            raise InvalidId(f"{value!r} is not a valid {scheme} id")
    for name in ("isbn_10", "isbn_13"):
        value = getattr(ids, name, None)
        if value and not _ISBN.fullmatch(value.replace("-", "")):
            raise InvalidId(f"{value!r} is not a valid isbn id")


def capable_sources(method: str, scheme: str, kind: Optional[str],
                    provider: Optional[str] = None) -> List[CatalogSource]:
    """The available sources that can answer, best first. Raises
    :class:`NotSupported` when there are none."""
    if provider is not None:
        source = _SOURCES.get(provider)
        if source is None or not source.can(method, scheme, kind):
            what = f"{method} of {kind} by {scheme}" if kind else f"{method} by {scheme}"
            raise NotSupported(f"provider {provider!r} cannot answer {what}", provider)
        if not source.available():
            raise NotSupported(f"provider {provider!r} is not available (missing configuration)", provider)
        return [source]
    candidates = [s for s in _SOURCES.values() if s.can(method, scheme, kind)]
    usable = sorted((s for s in candidates if s.available()), key=lambda s: (s.rank(method), s.name))
    if not usable:
        what = f"{method} of {kind} by {scheme}" if kind else f"{method} by {scheme}"
        if candidates:
            names = ", ".join(sorted(s.name for s in candidates))
            raise NotSupported(f"no available provider answers {what} (unavailable: {names})")
        raise NotSupported(f"no provider answers {what}")
    return usable


def ask(method: str, scheme: str, value: str, kind: Optional[str] = None, *,
        provider: Optional[str] = None, refresh: bool = False, children: bool = True,
        title: Optional[str] = None, year: Optional[int] = None) -> Answer:
    """Ask the capable sources ``method`` about ``scheme:value``. ``title`` and
    ``year`` name the work for ``variants``, which a catalogue of variants
    searches by title.

    Raises :class:`ValueError` for a malformed question and
    :class:`NotSupported` when no available source can answer it."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}")
    explicit = bool((kind or "").strip())
    scheme, value, kind = check_request(method, scheme, value, kind)
    sources = capable_sources(method, scheme, kind, provider)
    if method == "variants" and not (title or "").strip():
        raise ValueError("title is required for variants")
    from metadatarr.offline import layer

    if method == "lookup" and provider is None:
        served = layer.front_lookup(scheme, value, kind, children, refresh)
        if served is not None:
            return Answer(value=served[0], providers=[layer.PROVIDER], asked=[layer.PROVIDER], origin=served[1])
    work = ((title or "").strip(), year)
    key = (method, provider, scheme, value, kind, explicit, children, work)
    store = cache()
    if not refresh:
        hit, cached = store.get(key)
        if hit:
            return cached
    seconds = timeout()
    answer = Answer(value=None)
    holder = [False]
    failures: List[BaseException] = []
    token, failures_token = _TRUNCATED.set(holder), _FAILURES.set(failures)
    try:
        _ask_sources(method, scheme, value, kind, explicit, sources, children, refresh, seconds, answer, holder,
                     failures, work)
    finally:
        _TRUNCATED.reset(token)
        _FAILURES.reset(failures_token)
    if layer.enabled():
        answer.origin = layer.LIVE
    # An answer given while a better source was failing is not kept, so the
    # outage is not remembered for the whole cache lifetime.
    if answer.value is not None and not answer.errors:
        store.put(key, answer)
    return answer


def _error(source: str, stage: str, e: BaseException) -> ProviderError:
    return ProviderError(provider=source, stage=stage, error_type=type(e).__name__, message=_redact(str(e))[:500])


def _ask_sources(method, scheme, value, kind, explicit, sources, children, refresh, seconds, answer, holder,
                 failures, work=("", None)):
    with bypass_cache(refresh):
        for source in sources:
            answer.asked.append(source.name)
            holder[0] = False
            failures.clear()
            given = kind if explicit or not source.infers_kind else None
            if method == "lookup":
                call = lambda s=source: s.lookup(scheme, value, given, children=children, timeout=seconds)  # noqa: E731
            elif method == "credits":
                call = lambda s=source: s.credits(scheme, value, given, timeout=seconds)  # noqa: E731
            elif method == "extras":
                call = lambda s=source: s.extras(scheme, value, given, timeout=seconds)  # noqa: E731
            elif method == "variants":
                call = lambda s=source: s.variants(scheme, value, given, title=work[0], year=work[1],  # noqa: E731
                                                   timeout=seconds)
            else:
                call = lambda s=source: s.person(scheme, value, timeout=seconds)  # noqa: E731
            try:
                result = _call_with_timeout(call, seconds)
            except Exception as e:
                message = _redact(str(e))
                LOG.warning("catalogue %s failed during %s %s:%s: %s", source.name, method, scheme, value, message)
                answer.errors.append(ProviderError(provider=source.name, stage=method,
                                                   error_type=type(e).__name__, message=message[:500]))
                continue
            if result is not None:
                answer.value = result
                answer.providers.append(source.name)
                answer.truncated = holder[0]
                answer.errors.extend(_error(source.name, method, e) for e in failures)
                break
