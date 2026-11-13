# SPDX-License-Identifier: Apache-2.0
"""``dvdcompare_url`` is fetched only when it names https://www.dvdcompare.net.

Offline: the provider's HTTP session is replaced by a recorder, and one test
uses a loopback server to show that no connection is made.
"""
from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from mediavocab.models import ExternalIds  # noqa: E402

import metadatarr.resolve.base as resolve_base  # noqa: E402
from metadatarr.client import DVDCompareClient, check_dvdcompare_url  # noqa: E402
from metadatarr.resolve.providers.dvdcompare import DVDCompareProvider  # noqa: E402
from metadatarr.server.app import create_app  # noqa: E402
from metadatarr.server.config import ServerConfig  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "physical" / "dvdcompare_alien_bluray_fid16880.html"
GOOD = "https://www.dvdcompare.net/comparisons/film.php?fid=16880"

BAD_URLS = [
    "http://127.0.0.1/internal/admin?x=1",
    "http://localhost/etc",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/",
    "http://[::1]/",
    "http://2130706433/",
    "http://0x7f000001/",
    "http://0177.0.0.1/",
    "http://127.1/",
    "http://www.dvdcompare.net/comparisons/film.php?fid=1",
    "ftp://www.dvdcompare.net/x",
    "file:///etc/passwd",
    "https://www.dvdcompare.net.evil.test/comparisons/film.php?fid=1",
    "https://evil.test/www.dvdcompare.net",
    "https://evil.test/?www.dvdcompare.net",
    "https://www.dvdcompare.net@evil.test/",
    "https://user:pw@www.dvdcompare.net/comparisons/film.php?fid=1",
    "https://www.dvdcompare.net:8443/comparisons/film.php?fid=1",
    "https://www.dvdcompare.net:80/",
    "https://www.dvdcompare.net:@evil.test/",
    "https://www.dvdcompare.net\\@evil.test/",
    "https://evil.test\\.www.dvdcompare.net/",
    "https://www%2edvdcompare%2enet/",
    "https://www.dvdcompare%2Enet/",
    "https://www.dvdcompare.net%2eevil.test/",
    "https://xn--dvdcompare-xyz.net/",
    "https://www.dvdcomparе.net/",
    "https://www.dvdcompare.net./",
    "https://dvdcompare.net/",
    "https://WWW.DVDCOMPARE.NET.evil.test/",
    " https://www.dvdcompare.net/",
    "https://www.dvdcompare.net/ ",
    "https://www.dvdcompare.net/\nHost: evil.test",
    "https://www.dvdcompare.net/\tx",
    "https://www.dvdcompare.net/\x00",
    "//www.dvdcompare.net/",
    "www.dvdcompare.net/comparisons/film.php?fid=1",
    "https:///www.dvdcompare.net/",
    "https:www.dvdcompare.net/",
]


class _Resp:
    def __init__(self, status=200, headers=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self.text = text
        self.url = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    """Records every URL asked for and answers from a queue of responses."""

    def __init__(self, *responses):
        self.calls = []
        self.kwargs = []
        self._responses = list(responses)

    def get(self, url, **kw):
        self.calls.append(url)
        self.kwargs.append(kw)
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


@pytest.fixture
def page():
    return _Resp(text=FIXTURE.read_text(encoding="utf-8"))


def _provider(monkeypatch, session):
    provider = DVDCompareProvider()
    provider._client._session = session
    monkeypatch.setattr(resolve_base, "active_providers", lambda medium=None: [provider])
    return provider


def _post(route, url, **ids):
    client = TestClient(create_app(ServerConfig()))
    return client.post(route + "?refresh=true", json={"external_ids": {"extra": {"dvdcompare_url": url}, **ids}})


ROUTES = ["/api/v1/enrich", "/enrich"]


@pytest.mark.parametrize("url", BAD_URLS)
def test_check_rejects(url):
    with pytest.raises(ValueError):
        check_dvdcompare_url(url)


@pytest.mark.parametrize("url", [GOOD, "https://www.dvdcompare.net:443/comparisons/film.php?fid=1",
                                 "https://www.dvdcompare.net/"])
def test_check_accepts(url):
    assert check_dvdcompare_url(url) == url


@pytest.mark.parametrize("value", [None, 7, ["https://www.dvdcompare.net/"], {"u": 1}, b"https://www.dvdcompare.net/"])
def test_check_rejects_non_strings(value):
    with pytest.raises(ValueError):
        check_dvdcompare_url(value)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("url", BAD_URLS)
def test_route_rejects_and_never_fetches(monkeypatch, page, route, url):
    session = _Session(page)
    _provider(monkeypatch, session)
    resp = _post(route, url)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == "invalid id"
    assert resp.headers["cache-control"] == "no-store"
    assert session.calls == []


@pytest.mark.parametrize("route", ROUTES)
def test_route_rejects_bad_url_even_with_an_id(monkeypatch, page, route):
    session = _Session(page)
    _provider(monkeypatch, session)
    resp = _post(route, "http://127.0.0.1/x", dvdcompare_id="16880")
    assert resp.status_code == 422
    assert session.calls == []


@pytest.mark.parametrize("bad", BAD_URLS)
def test_client_rejects_without_the_route(page, bad):
    client = DVDCompareClient()
    client._session = session = _Session(page)
    with pytest.raises(ValueError):
        client.get_edition(bad)
    assert session.calls == []


@pytest.mark.parametrize("bad", BAD_URLS[:8])
def test_provider_rejects_without_the_route(monkeypatch, page, bad):
    provider = DVDCompareProvider()
    provider._client._session = session = _Session(page)
    assert provider.enrich(ExternalIds(extra={"dvdcompare_url": bad})) is None
    assert session.calls == []


def test_loopback_server_receives_nothing():
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        for url in (f"http://127.0.0.1:{port}/internal/admin?x=1", f"http://localhost:{port}/etc"):
            provider = DVDCompareProvider()
            assert provider.enrich(ExternalIds(extra={"dvdcompare_url": url})) is None
    finally:
        server.shutdown()
        server.server_close()
    assert hits == []


def test_redirect_off_host_is_not_followed(page):
    client = DVDCompareClient()
    client._session = session = _Session(
        _Resp(302, {"Location": "http://127.0.0.1/internal"}), page)
    with pytest.raises(ValueError):
        client.get_edition(GOOD)
    assert session.calls == [GOOD]
    assert all(kw.get("allow_redirects") is False for kw in session.kwargs)


@pytest.mark.parametrize("location", [
    "https://evil.test/", "//evil.test/x", "https://www.dvdcompare.net@evil.test/",
    "https://www.dvdcompare.net.evil.test/", "\\\\evil.test\\x",
])
def test_redirect_variants_off_host_are_not_followed(page, location):
    client = DVDCompareClient()
    client._session = session = _Session(_Resp(301, {"Location": location}), page)
    with pytest.raises(ValueError):
        client.get_edition(GOOD)
    assert session.calls == [GOOD]


def test_redirect_on_host_is_followed(page):
    client = DVDCompareClient()
    client._session = session = _Session(
        _Resp(302, {"Location": "/comparisons/film.php?fid=16880&x=1"}), page)
    edition = client.get_edition(GOOD)
    assert edition.director == "Ridley Scott"
    assert session.calls == [GOOD, "https://www.dvdcompare.net/comparisons/film.php?fid=16880&x=1"]


def _chain(page, hops):
    redirects = [_Resp(302, {"Location": f"/comparisons/film.php?fid={n}"}) for n in range(hops)]
    return _Session(*redirects, page)


def test_five_redirects_are_followed(page):
    client = DVDCompareClient()
    client._session = session = _chain(page, 5)
    assert client.get_edition(GOOD).director == "Ridley Scott"
    assert len(session.calls) == 6


def test_six_redirects_raise(page):
    import requests

    client = DVDCompareClient()
    client._session = session = _chain(page, 6)
    with pytest.raises(requests.TooManyRedirects):
        client.get_edition(GOOD)
    assert len(session.calls) == 6


def test_search_does_not_follow_redirects(page):
    import requests

    class Poster:
        def __init__(self):
            self.calls = []

        def post(self, url, **kw):
            self.calls.append((url, kw))
            return _Resp(307, {"Location": "http://127.0.0.1/internal"})

    client = DVDCompareClient()
    client._session = poster = Poster()
    with pytest.raises(requests.HTTPError):
        client.search("Alien")
    assert len(poster.calls) == 1
    assert poster.calls[0][1]["allow_redirects"] is False


def test_redirect_loop_is_bounded():
    import requests

    client = DVDCompareClient()
    client._session = session = _Session(_Resp(302, {"Location": GOOD}))
    with pytest.raises(requests.TooManyRedirects):
        client.get_edition(GOOD)
    assert len(session.calls) <= 10


@pytest.mark.parametrize("route", ROUTES)
def test_enrich_by_url_returns_external_ids(monkeypatch, page, route):
    session = _Session(page)
    _provider(monkeypatch, session)
    resp = _post(route, GOOD)
    assert resp.status_code == 200, resp.text
    assert session.calls == [GOOD]
    body = resp.json()
    assert body["dvdcompare_id"] == "16880"
    assert body["extra"]["dvdcompare_url"] == GOOD


@pytest.mark.parametrize("route", ROUTES)
def test_empty_id_and_empty_url_are_ignored(monkeypatch, page, route):
    session = _Session(page)
    _provider(monkeypatch, session)
    assert _post(route, "", dvdcompare_id="").status_code == 200
    assert session.calls == []


def test_mappings_ignore_structured_extra_values():
    from metadatarr.resolve.entities import EntityRole
    from metadatarr.resolve.mappings import apply_mappings

    ids = ExternalIds(extra={"dvdcompare_cut_runtimes": [{"cut": "Theatrical", "runtime_seconds": 7020}]})
    for role in EntityRole:
        assert apply_mappings(role, ids) == ids
