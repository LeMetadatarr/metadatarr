"""Smoke check: License.from_spdx + is_open."""
from __future__ import annotations

from _common import fail, pass_
from mediavocab.models.license import License


def main() -> int:
    # is_open(): permits at least non-commercial, no-derivative redistribution
    # — every CC-* and PD/CC0 counts; only "all_rights_reserved"/empty/unknown
    # do not. Commercial/derivatives axes are independent and checked separately.
    cases = [
        # (spdx,            open, public_domain, commercial, derivatives, share_alike)
        ("CC-BY-4.0",       True,  False, True,  True,  False),
        ("CC-BY-NC-4.0",    True,  False, False, True,  False),
        ("CC0-1.0",         True,  True,  True,  True,  False),
        ("CC-BY-SA-4.0",    True,  False, True,  True,  True),
        ("CC-BY-ND-4.0",    True,  False, True,  False, False),
        ("CC-BY-NC-SA-4.0", True,  False, False, True,  True),
        ("CC-BY-NC-ND-4.0", True,  False, False, False, False),
    ]
    for spdx, ex_open, ex_pd, ex_com, ex_der, ex_sa in cases:
        lic = License.from_spdx(spdx)
        if lic.is_open() is not ex_open:
            return fail(f"{spdx}: is_open()={lic.is_open()} expected {ex_open}")
        if lic.is_public_domain is not ex_pd:
            return fail(f"{spdx}: is_public_domain={lic.is_public_domain} expected {ex_pd}")
        if lic.commercial is not ex_com:
            return fail(f"{spdx}: commercial={lic.commercial} expected {ex_com}")
        if lic.derivatives is not ex_der:
            return fail(f"{spdx}: derivatives={lic.derivatives} expected {ex_der}")
        if lic.share_alike is not ex_sa:
            return fail(f"{spdx}: share_alike={lic.share_alike} expected {ex_sa}")
    unk = License.from_spdx("Proprietary")
    if unk.is_open():
        return fail("Unknown SPDX should not be open")
    return pass_(f"License.from_spdx covers {len(cases)} CC + 1 unknown case correctly")


if __name__ == "__main__":
    raise SystemExit(main())
