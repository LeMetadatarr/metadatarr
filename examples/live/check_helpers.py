"""Smoke check: mediavocab 0.3 helpers (best_release, episodes_of)."""
from __future__ import annotations

from _common import fail, pass_
from mediavocab import MediaType, Release, ReleasePackaging, VariantKind, Work
from mediavocab.helpers import best_release, episodes_of


def main() -> int:
    series = Work(title="Doctor Who", media_type=MediaType.EPISODIC_SERIES,
                  series_title="Doctor Who")
    e1 = Work(title="Pilot", media_type=MediaType.EPISODIC_SERIES,
              series_title="Doctor Who", season=1, episode=1)
    e2 = Work(title="Second", media_type=MediaType.EPISODIC_SERIES,
              series_title="Doctor Who", season=1, episode=2)
    eps = episodes_of(series, [series, e2, e1])
    if [e.episode for e in eps] != [1, 2]:
        return fail(f"episodes_of did not order: {[e.episode for e in eps]}")

    w = Work(title="Blade Runner", media_type=MediaType.MOVIE)
    w_dc = Work(title="Blade Runner", media_type=MediaType.MOVIE,
                variant_kind=VariantKind.DIRECTORS)
    sd = Release(work=w, resolution="480p")
    uhd = Release(work=w_dc, resolution="2160p")
    boot = Release(work=w, resolution="2160p",
                   packaging=ReleasePackaging.BOOTLEG)
    best = best_release(sd, uhd, boot)
    if best is not uhd:
        return fail(f"best_release picked the wrong release")
    return pass_("episodes_of orders by (season, episode); best_release "
                 "prefers DIRECTORS 2160p over BOOTLEG 2160p over SD")


if __name__ == "__main__":
    raise SystemExit(main())
