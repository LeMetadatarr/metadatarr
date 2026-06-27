# Testing providers

Provider tests must be **offline and deterministic** — no live network in the
suite. The whole resolver is silent-failure, so a test that quietly hits the
network would pass even when the provider is broken. Patch the transport and
feed it a known payload.

## Running the suite

```bash
pip install .[test]
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` keeps third-party pytest plugins from
loading, which is what CI uses.

## Two offline patterns

### 1. Mock the HTTP session (JSON APIs)

Patch the provider's HTTP entry point and return a fake response. This is the
TMDB/TVDB cassette style — see [`tests/test_tmdb_cassette.py`](../tests/test_tmdb_cassette.py).

```python
import os
from unittest.mock import MagicMock, patch
from mediavocab.models.signals import Signals
from metadatarr.resolve.providers.tmdb import TMDBProvider


def _response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def test_movie_match():
    p = TMDBProvider()
    payload = {"results": [{"id": 27205, "title": "Inception",
                            "release_date": "2010-07-16"}]}
    sess = MagicMock()
    sess.get.return_value = _response(payload)
    with patch.dict(os.environ, {"TMDB_API_KEY": "fake-key"}):
        with patch("metadatarr.resolve.providers.tmdb._http", return_value=sess):
            m = p.lookup(Signals(title="Inception", year=2010))
    assert m.external_ids.tmdb_movie == 27205
```

Always patch at the seam the provider actually calls (its `_http` factory, or
the upstream client method) — patch what the *provider* imports, not where the
symbol is defined.

### 2. Committed response fixtures (HTML scrapers)

For HTML scrapers, capture a real page once, commit it under
`tests/fixtures/<area>/`, and serve it from disk. See
[`tests/test_physical_clients.py`](../tests/test_physical_clients.py) and
`tests/fixtures/physical/`.

```python
from pathlib import Path
FIXTURES = Path(__file__).parent / "fixtures" / "physical"

def test_bluray_parse():
    html = (FIXTURES / "bluray_com_moon_17549.html").read_text(encoding="utf-8")
    # patch the client's fetch to return `html`, then assert on the parse
```

## The per-provider smoke contract

Every registered provider is covered by a parametrized smoke test
(`tests/test_providers_smoke.py`) that asserts the universal contract with **no
network**:

- `is_available()` returns a `bool` and never raises.
- `lookup(signals)` returns `ProviderMatch | None` and never raises — even when
  the upstream transport blows up. The test injects a failing session to prove
  the swallow-log-return-None contract holds.

When you add a provider it is picked up automatically (the test parametrizes
over the live registry), so there is nothing to wire up — but a provider that
raises on a transport error, or returns the wrong type, will fail it.

## Tips

- Test the **unavailable** path too (missing key/dep → `is_available()` is
  `False`), the **no-results** path (`lookup` → `None`), and the **error** path
  (transport raises → `lookup` → `None`, with a warning logged).
- Use `match_quality` in assertions sparingly; prefer asserting on the emitted
  `external_ids` / `signals` fields, which are the contract callers depend on.
- Genre/field emission is guarded centrally
  (`tests/test_provider_genre_emission.py`); if your provider emits
  `content_genres`, make sure they come from `GENRE_*` constants.
