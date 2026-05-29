# TODO — metadatarr

## Open issues
None open.

## Gaps
- [ ] No mypy/typecheck config; only ruff is enabled. Consider adding a typecheck pass given the Pydantic-heavy, multi-provider surface.
- [ ] Coverage intentionally omits `resolve/providers/*` (integration-tested via `examples/`); the live example scripts are not run in CI, so provider regressions can land undetected.
- [ ] Repo root carries stray runtime artefacts: `.coverage`, `fanfix_edits.jsonl`, `watchlist_state.json`, `audit.md`, `metadatarr.egg-info/`, `__pycache__/`. Confirm these are ignored/untracked rather than committed.

## Code TODOs
None found. (Only grep match: `metadatarr/resolve/providers/pylordofporn.py:12` references "Star Wars XXX" as an example title string, not a TODO marker.)
