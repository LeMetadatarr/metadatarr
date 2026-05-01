"""Disambiguation signals — the bag of facts we compare to decide whether
two rows describe the *same work*.

Comparison rules (encoded in :func:`compare`):

- A signal absent on either side is **not** a disagreement.
- All overlapping signals must agree → matched.
- Any single overlapping signal disagrees → conflict (caller quarantines).

Tolerances are intentionally conservative; loosen them on a per-medium basis
at the call site if needed (e.g. live recordings vs studio cuts).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Tolerances (defaults)
# ---------------------------------------------------------------------------
TITLE_FUZZY_MIN = 0.92
ARTIST_FUZZY_MIN = 0.90
YEAR_TOLERANCE = 1                 # years
RUNTIME_TOLERANCE_S = 5.0          # seconds — fallback when no medium set

# Per-medium runtime tolerances. TV episode runtimes are reported by every
# upstream rounded to whole minutes; songs and books need much tighter
# windows; movies sit in between because of recut/extended releases.
RUNTIME_TOLERANCE_BY_MEDIUM_S: Dict[str, float] = {
    "movie": 120.0,
    "tv": 30.0,
    "music": 3.0,
    "music_video": 30.0,   # concert films / official MVs vary widely in length
    "book": 0.0,
    "podcast": 30.0,
    "other": 5.0,
}


class Medium(str, Enum):
    MOVIE = "movie"
    TV = "tv"
    MUSIC = "music"
    MUSIC_VIDEO = "music_video"  # concert film, official music video, live performance
    BOOK = "book"
    PODCAST = "podcast"
    OTHER = "other"


class VariantKind(str, Enum):
    # Film variants
    THEATRICAL = "theatrical"
    DIRECTORS = "directors"
    EXTENDED = "extended"
    FANEDIT = "fanedit"
    COLORIZED = "colorized"
    UPSCALED = "upscaled"
    # Album variants
    STANDARD = "standard"
    DELUXE = "deluxe"
    BONUS_TRACKS = "bonus_tracks"
    REISSUE = "reissue"
    COMPILATION = "compilation"
    # Shared
    REGIONAL = "regional"
    REMASTERED = "remastered"
    OTHER = "other"


class Signals(BaseModel):
    """Bag of signals extracted from a row, normalized for comparison."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    artist: Optional[str] = None       # for music/podcast: artist; for video: director
    year: Optional[int] = None
    country: Optional[str] = None      # ISO 3166-1 alpha-2
    runtime: Optional[float] = None    # seconds
    medium: Optional[Medium] = None
    language: Optional[str] = None     # ISO 639-1
    season: Optional[int] = None       # TV episodes only
    episode: Optional[int] = None      # TV episodes only

    # Release-variant signals
    variant_kind: Optional[VariantKind] = None
    edition: Optional[str] = None      # free-text edition name
    region: Optional[str] = None       # ISO 3166-1 alpha-2; distinct from work-origin country
    source_format: Optional[str] = None  # "4K", "Blu-ray", "Vinyl", "Cassette", …
    include_variants: bool = False     # fan out to variant-aware providers


class SignalConflict(BaseModel):
    """Single-field disagreement between two Signals bags."""

    model_config = ConfigDict(extra="forbid")

    signal: str
    ours: Any
    theirs: Any


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_FEAT_RE = re.compile(
    r"\s*(?:\(|\[)?\s*(?:feat|ft|featuring)\.?\s+[^)\]]*[)\]]?", re.IGNORECASE,
)
_PARENS_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)


def _strip_diacritics(text: str) -> str:
    """Fold combining marks so 'café' compares equal to 'cafe'.

    Uses NFKD decomposition + drop combining-marks. Keeps base characters
    of any script (Cyrillic, CJK, Greek) untouched — only the accents and
    diacritics disappear. For full Cyrillic↔Latin transliteration, callers
    can layer ``unidecode`` on top before passing strings to compare().
    """
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(ch)
    )


def _normalize_text(text: str) -> str:
    text = _strip_diacritics(text or "").lower()
    text = _FEAT_RE.sub(" ", text)
    text = _PARENS_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def fuzzy_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_text(a), _normalize_text(b)).ratio()


# ---------------------------------------------------------------------------
# Pairwise comparison
# ---------------------------------------------------------------------------

def _agree_year(a: int, b: int, tolerance: int = YEAR_TOLERANCE) -> bool:
    return abs(int(a) - int(b)) <= tolerance


def _agree_runtime(a: float, b: float, tolerance: float = RUNTIME_TOLERANCE_S) -> bool:
    return abs(float(a) - float(b)) <= tolerance


def _agree_string(a: str, b: str, threshold: float) -> bool:
    return fuzzy_ratio(a, b) >= threshold


def compare(ours: Signals, theirs: Signals) -> List[SignalConflict]:
    """Return the list of *overlapping* signals that disagree.

    Empty list ⇒ matched (no overlap counts as agreement, by design).
    """
    conflicts: List[SignalConflict] = []

    if ours.title and theirs.title and not _agree_string(
        ours.title, theirs.title, TITLE_FUZZY_MIN
    ):
        conflicts.append(SignalConflict(signal="title", ours=ours.title,
                                        theirs=theirs.title))

    if ours.artist and theirs.artist and not _agree_string(
        ours.artist, theirs.artist, ARTIST_FUZZY_MIN
    ):
        conflicts.append(SignalConflict(signal="artist", ours=ours.artist,
                                        theirs=theirs.artist))

    if ours.year is not None and theirs.year is not None and not _agree_year(
        ours.year, theirs.year
    ):
        conflicts.append(SignalConflict(signal="year", ours=ours.year,
                                        theirs=theirs.year))

    if ours.country and theirs.country and ours.country.upper() != theirs.country.upper():
        conflicts.append(SignalConflict(signal="country", ours=ours.country,
                                        theirs=theirs.country))

    if ours.runtime is not None and theirs.runtime is not None:
        # Pick the tighter side's medium so a movie/TV mix doesn't slacken
        # the tolerance unexpectedly. When neither side declares a medium
        # we fall back to the historical 5-second default.
        m_value = (ours.medium or theirs.medium).value if (ours.medium or theirs.medium) else None
        tol = RUNTIME_TOLERANCE_BY_MEDIUM_S.get(m_value, RUNTIME_TOLERANCE_S)
        if not _agree_runtime(ours.runtime, theirs.runtime, tolerance=tol):
            conflicts.append(SignalConflict(signal="runtime", ours=ours.runtime,
                                            theirs=theirs.runtime))

    if ours.season is not None and theirs.season is not None and ours.season != theirs.season:
        conflicts.append(SignalConflict(signal="season", ours=ours.season,
                                        theirs=theirs.season))

    if ours.episode is not None and theirs.episode is not None and ours.episode != theirs.episode:
        conflicts.append(SignalConflict(signal="episode", ours=ours.episode,
                                        theirs=theirs.episode))

    if ours.medium and theirs.medium and ours.medium != theirs.medium:
        conflicts.append(SignalConflict(signal="medium",
                                        ours=ours.medium.value,
                                        theirs=theirs.medium.value))

    if ours.language and theirs.language and ours.language.lower() != theirs.language.lower():
        conflicts.append(SignalConflict(signal="language", ours=ours.language,
                                        theirs=theirs.language))

    if ours.variant_kind and theirs.variant_kind and ours.variant_kind != theirs.variant_kind:
        conflicts.append(SignalConflict(signal="variant_kind",
                                        ours=ours.variant_kind.value,
                                        theirs=theirs.variant_kind.value))

    if ours.region and theirs.region and ours.region.upper() != theirs.region.upper():
        conflicts.append(SignalConflict(signal="region", ours=ours.region,
                                        theirs=theirs.region))

    if (ours.source_format and theirs.source_format
            and ours.source_format.lower() != theirs.source_format.lower()):
        conflicts.append(SignalConflict(signal="source_format",
                                        ours=ours.source_format,
                                        theirs=theirs.source_format))

    if ours.edition and theirs.edition and ours.edition.lower() != theirs.edition.lower():
        conflicts.append(SignalConflict(signal="edition", ours=ours.edition,
                                        theirs=theirs.edition))

    return conflicts


def merged(*bags: Signals) -> Signals:
    """First non-None value wins, per field."""
    fields = ("title", "artist", "year", "country", "runtime", "medium",
              "language", "season", "episode",
              "variant_kind", "edition", "region", "source_format")
    out: Dict[str, Any] = {}
    for f in fields:
        for b in bags:
            v = getattr(b, f, None)
            if v not in (None, ""):
                out[f] = v
                break
    out["include_variants"] = any(getattr(b, "include_variants", False) for b in bags)
    return Signals(**out)


def match_quality(local: Signals, candidate: Signals) -> float:
    """Score how well ``candidate`` matches ``local`` on the range ``[0.0, 1.0]``.

    Used by providers to scale their base confidence so a strong upstream
    source that returned a *bad* candidate doesn't outvote a weaker source
    that returned a perfect one. Heuristic, intentionally simple:

    - title fuzzy ratio is the main driver (1.0 if either side missing);
    - hard agreement on year and medium adds up to a small bonus.
    """
    score = 1.0
    if local.title and candidate.title:
        score *= fuzzy_ratio(local.title, candidate.title)
    if local.year is not None and candidate.year is not None:
        if _agree_year(local.year, candidate.year):
            score *= 1.0
        else:
            # Year mismatch is a strong signal it's the wrong record.
            score *= 0.5
    if local.medium and candidate.medium and local.medium != candidate.medium:
        score *= 0.5
    return max(0.0, min(score, 1.0))


def signal_hash(s: Signals) -> str:
    """A stable hash over the immutable signals — used as the canonical_id seed."""
    parts = [
        _normalize_text(s.title or ""),
        _normalize_text(s.artist or ""),
        str(s.year) if s.year is not None else "",
        (s.country or "").upper(),
        f"{round(s.runtime):d}" if s.runtime is not None else "",
        s.medium.value if s.medium else "",
        (s.language or "").lower(),
        f"S{s.season}" if s.season is not None else "",
        f"E{s.episode}" if s.episode is not None else "",
        s.variant_kind.value if s.variant_kind else "",
        (s.edition or "").lower(),
        (s.region or "").upper(),
        (s.source_format or "").lower(),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
