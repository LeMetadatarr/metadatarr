"""Smoke check: ReleaseRelation — per-edition lineage."""
from __future__ import annotations

from _common import fail, pass_
from mediavocab import MediaType, Release, Work
from mediavocab.models.work import ReleaseRelation
from mediavocab.taxonomy.relation import ReleaseRelationKind


def main() -> int:
    w = Work(title="Blade Runner", media_type=MediaType.MOVIE, year=1982)
    stereo_2017 = Release(work=w, container="Blu-ray", resolution="2160p",
                          audio_channels="stereo", release_date="2017-09-05")
    atmos_2025 = Release(work=w, container="Blu-ray", resolution="2160p",
                         audio_channels="Atmos", release_date="2025-09-05")
    rel = ReleaseRelation(kind=ReleaseRelationKind.SUPERSEDES,
                          target=stereo_2017,
                          note="2025 Atmos remaster")
    if rel.kind is not ReleaseRelationKind.SUPERSEDES:
        return fail("ReleaseRelation.kind not preserved")
    if rel.target.audio_channels != "stereo":
        return fail("ReleaseRelation.target not preserved")
    return pass_(f"ReleaseRelation: 2025 Atmos {atmos_2025.audio_channels} "
                 f"SUPERSEDES 2017 {rel.target.audio_channels}")


if __name__ == "__main__":
    raise SystemExit(main())
