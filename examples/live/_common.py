"""Shared helpers for live checks.

Each check is an executable script that prints a single ``PASS:`` / ``FAIL:``
/ ``SKIP:`` line and exits with a matching status (0 / 1 / 0).
"""
from __future__ import annotations

import sys


def pass_(msg: str) -> int:
    print(f"PASS: {msg}")
    return 0


def fail(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return 1


def skip(msg: str) -> int:
    print(f"SKIP: {msg}", file=sys.stderr)
    return 0


def first_match(candidates, provider: str):
    return next((m for m in candidates if m.provider == provider), None)
