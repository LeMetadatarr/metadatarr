"""Smoke check: Programme + Schedule construction."""
from __future__ import annotations

from _common import fail, pass_
from mediavocab import EntityKind, EntityRef
from mediavocab.models.work import Programme, Schedule


def main() -> int:
    bbc1 = EntityRef(name="BBC One", kind=EntityKind.SERIES,
                     external_ids={"tvmaze_network_id": "12"})
    show = EntityRef(name="Doctor Who", kind=EntityKind.SERIES,
                     external_ids={"imdb": "tt0436992"})
    p = Programme(work=show, channel=bbc1,
                  starts_at="2026-05-06T19:00:00+01:00",
                  ends_at="2026-05-06T19:45:00+01:00",
                  is_repeat=True)
    s = Schedule(channel=bbc1, programmes=[p],
                 valid_from="2026-05-06T00:00:00+01:00",
                 valid_until="2026-05-07T00:00:00+01:00",
                 source="tvmaze")
    if len(s.programmes) != 1 or not s.programmes[0].is_repeat:
        return fail("Schedule did not round-trip Programme.is_repeat")
    if s.channel.name != "BBC One":
        return fail("Schedule.channel was not preserved")
    return pass_(f"Programme/Schedule built: {s.channel.name} has "
                 f"{len(s.programmes)} programme(s)")


if __name__ == "__main__":
    raise SystemExit(main())
