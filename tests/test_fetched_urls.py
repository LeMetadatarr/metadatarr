# SPDX-License-Identifier: Apache-2.0
"""Bandcamp and SoundCloud URL keys are fetched only when they pass the host rules.

Offline: name resolution is replaced by a table that raises for unknown names,
and the libraries are replaced by recorders.  One test points the real
libraries at a loopback server to show that no connection is made.
"""
from __future__ import annotations

import http.server
import socket
import threading
import types

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from mediavocab.models import ExternalIds  # noqa: E402

import metadatarr.client as client_mod  # noqa: E402
import metadatarr.resolve.base as resolve_base  # noqa: E402
from metadatarr.client import (  # noqa: E402
    check_bandcamp_url, check_fetched_urls, check_soundcloud_url, fetchable_url)
from metadatarr.resolve.providers.bandcamp import BandcampProvider  # noqa: E402
from metadatarr.resolve.providers.soundcloud import SoundCloudProvider  # noqa: E402
from metadatarr.server.app import create_app  # noqa: E402
from metadatarr.server.config import ServerConfig  # noqa: E402

ROUTES = ["/api/v1/enrich", "/enrich"]
SC_KEYS = ["soundcloud_track_url", "soundcloud_artist_url"]
BC_KEYS = ["bandcamp_track_url", "bandcamp_album_url", "bandcamp_artist_url"]
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """Name table; any name not in it fails to resolve.  ``dns.calls`` lists the lookups."""
    table = {}
    calls = []

    def getaddrinfo(host, port, *args, **kw):
        calls.append(host)
        if host not in table:
            raise socket.gaierror(socket.EAI_NONAME, "not in table")
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (a, port, 0, 0) if ":" in a else (a, port)) for a in table[host]]

    monkeypatch.setattr(client_mod, "socket", types.SimpleNamespace(
        getaddrinfo=getaddrinfo, SOCK_STREAM=socket.SOCK_STREAM))
    return types.SimpleNamespace(table=table, calls=calls)


SC_BAD = [
    "http://soundcloud.com/acidkid",
    "file:///etc/passwd",
    "ftp://soundcloud.com/x",
    "data:text/html,x",
    "javascript:alert(1)",
    "http://127.0.0.1/x",
    "http://169.254.169.254/latest",
    "https://169.254.169.254/latest",
    "https://2130706433/",
    "https://0x7f000001/",
    "https://0177.0.0.1/",
    "https://127.1/",
    "https://[::1]/",
    "https://localhost/",
    "https://soundcloud.com@evil.test/",
    "https://user:pw@soundcloud.com/x",
    "https://soundcloud.com:8443/x",
    "https://soundcloud.com:80/x",
    "https://soundcloud.com:/x",
    "https://soundcloud.com:@evil.test/",
    "https://soundcloud.com:443@evil.test/",
    "https://soundcloud.com\\@evil.test/",
    "https://evil.test\\.soundcloud.com/",
    "https://soundcloud.com./x",
    "https://on.soundcloud.com./x",
    "https://soundcloud.com.evil.test/",
    "https://evilsoundcloud.com/",
    "https://evil.test/soundcloud.com",
    "https://evil.test/?soundcloud.com",
    "https://evil.test/#soundcloud.com",
    "https://xn--soundclod-j5a.com/",
    "https://soundcloud.com.xn--p1ai/",
    "https://xn--soundcloud-9ya.com/",
    "https://soundclоud.com/",
    "https://soundcloud%2ecom/",
    "https://soundcloud.com%2eevil.test/",
    "https://sound cloud.com/",
    "https://.soundcloud.com/",
    "https://a..soundcloud.com/",
    "https://-a.soundcloud.com/",
    "https://a_b.soundcloud.com/",
    " https://soundcloud.com/x",
    "https://soundcloud.com/x ",
    "https://soundcloud.com/\nHost: evil.test",
    "https://soundcloud.com/\tx",
    "https://soundcloud.com/\x00",
    "https://soundcloud.com/a\\b",
    "https://soundcloud.com/\u00fc",
    "//soundcloud.com/x",
    "soundcloud.com/x",
    "https:///soundcloud.com/x",
    "https:soundcloud.com/x",
    "",
]
SC_GOOD = [
    "https://soundcloud.com/acidkid",
    "https://soundcloud.com/",
    "https://on.soundcloud.com/AbC123",
    "https://www.soundcloud.com/x",
    "https://m.soundcloud.com/a/b?x=1#frag",
    "https://api.soundcloud.com/tracks/1",
    "https://soundcloud.com:443/x",
    "https://xn--bcher-kva.soundcloud.com/x",
]
SC_NORMALISED = {
    "https://SoundCloud.com/Acid-Kid": "https://soundcloud.com/Acid-Kid",
    "https://soundcloud.COM/x": "https://soundcloud.com/x",
    "https://ON.SoundCloud.com:443/AbC?Q=A#F": "https://on.soundcloud.com:443/AbC?Q=A#F",
}

BC_BAD_STATIC = [
    "http://artist.bandcamp.com/track/x",
    "http://127.0.0.1/x",
    "file:///etc/passwd",
    "ftp://artist.bandcamp.com/x",
    "data:text/html,x",
    "javascript:alert(1)",
    "https://127.0.0.1/x",
    "https://127.0.0.1:8080/x",
    "https://169.254.169.254/latest",
    "https://10.0.0.5/",
    "https://100.64.0.1/",
    "https://8.8.8.8/",
    "https://2130706433/",
    "https://0x7f000001/",
    "https://0x7f.0x0.0x0.0x1/",
    "https://0177.0.0.1/",
    "https://0177.0.0.01/",
    "https://127.1/",
    "https://127.0.1/",
    "https://1.1/",
    "https://017700000001/",
    "https://[::1]/",
    "https://[::ffff:127.0.0.1]/",
    "https://[::ffff:7f00:1]/",
    "https://[2606:2800:220:1::1]/",
    "https://localhost/",
    "https://localhost./",
    "https://LOCALHOST/",
    "https://intranet/",
    "https://bandcamp/",
    "https://artist.bandcamp.com@evil.test/",
    "https://user:pw@artist.bandcamp.com/",
    "https://user@artist.bandcamp.com/",
    "https://artist.bandcamp.com:8443/",
    "https://artist.bandcamp.com:80/",
    "https://artist.bandcamp.com:/",
    "https://artist.bandcamp.com:@evil.test/",
    "https://artist.bandcamp.com\\@evil.test/",
    "https://evil.test\\.bandcamp.com/",
    "https://artist.bandcamp.com./",
    "https://example.com./",
    "https://artïst.bandcamp.com/",
    "https://artist.bandcamp.com%2eevil.test/",
    "https://art ist.bandcamp.com/",
    "https://.bandcamp.com/",
    "https://a..bandcamp.com/",
    "https://-a.bandcamp.com/",
    "https://a_b.bandcamp.com/",
    "https://a.b.0x7f/",
    "https://a.b.1/",
    "https://a.b.123/",
    "https://a.b.x/",
    " https://artist.bandcamp.com/",
    "https://artist.bandcamp.com/ ",
    "https://artist.bandcamp.com/\nHost: evil.test",
    "https://artist.bandcamp.com/\x00",
    "https://artist.bandcamp.com/a\\b",
    "https://artist.bandcamp.com/\u00fc",
    "//artist.bandcamp.com/",
    "artist.bandcamp.com/",
    "https:///artist.bandcamp.com/",
    "https:artist.bandcamp.com/",
    "https://" + "a" * 64 + ".example.com/",
    "https://" + ".".join(["abcdefghij"] * 26) + ".com/",
    "",
]
# Name -> addresses for hosts that are well formed but must be refused.
BC_BAD_RESOLVED = {
    "loopback4.example": ["127.0.0.1"],
    "loopback4-high.example": ["127.255.255.254"],
    "loopback6.example": ["::1"],
    "private-a.example": ["10.1.2.3"],
    "private-b.example": ["172.16.0.1"],
    "private-c.example": ["192.168.0.1"],
    "private6.example": ["fc00::1"],
    "linklocal.example": ["169.254.169.254"],
    "linklocal6.example": ["fe80::1"],
    "linklocal6-scope.example": ["fe80::1%eth0"],
    "cgnat-low.example": ["100.64.0.1"],
    "cgnat-high.example": ["100.127.255.254"],
    "mapped-loopback.example": ["::ffff:127.0.0.1"],
    "mapped-private.example": ["::ffff:10.0.0.1"],
    "mapped-metadata.example": ["::ffff:169.254.169.254"],
    "mapped-cgnat.example": ["::ffff:100.64.0.1"],
    "unspecified4.example": ["0.0.0.0"],
    "unspecified6.example": ["::"],
    "multicast4.example": ["224.0.0.1"],
    "multicast6.example": ["ff02::1"],
    "reserved.example": ["240.0.0.1"],
    "broadcast.example": ["255.255.255.255"],
    "nat64-loopback.example": ["64:ff9b::7f00:1"],
    "sixtofour-loopback.example": ["2002:7f00:1::"],
    "mixed-v4.example": [PUBLIC_V4, "10.0.0.1"],
    "mixed-v4-first.example": ["10.0.0.1", PUBLIC_V4],
    "mixed-v6.example": [PUBLIC_V4, PUBLIC_V6, "::1"],
    "mixed-mapped.example": [PUBLIC_V6, "::ffff:127.0.0.1"],
    "mixed-cgnat.example": [PUBLIC_V4, "100.64.0.1"],
    "localhost-subdomain.localhost": [PUBLIC_V4],
    "empty.example": [],
    "compat-loopback.example": ["::7f00:1"],
    "compat-private.example": ["::a00:1"],
    "compat-public-looking.example": ["::808:808"],
    "sitelocal.example": ["fec0::1"],
    "sitelocal-high.example": ["feff:ffff::1"],
    "mixed-sitelocal.example": [PUBLIC_V6, "fec0::1"],
    "nxdomain.example": None,
}
BC_BAD_RESOLVED_URLS = [f"https://{h}/" for h in BC_BAD_RESOLVED]
BC_GOOD = {
    "https://artist.bandcamp.com/track/x": ["artist.bandcamp.com", [PUBLIC_V4]],
    "https://artist.bandcamp.com/": ["artist.bandcamp.com", [PUBLIC_V6]],
    "https://artist.bandcamp.com:443/album/y?x=1": ["artist.bandcamp.com", [PUBLIC_V4, PUBLIC_V6]],
    "https://music.example.com/album/a": ["music.example.com", [PUBLIC_V4]],
    "https://a.b.c.example.co.uk/": ["a.b.c.example.co.uk", [PUBLIC_V4]],
    "https://xn--bcher-kva.example/": ["xn--bcher-kva.example", [PUBLIC_V4]],
    "https://artist.xn--p1ai/": ["artist.xn--p1ai", [PUBLIC_V4]],
    "https://artist-1.bandcamp.com/": ["artist-1.bandcamp.com", [PUBLIC_V4]],
}
BC_NORMALISED = {
    "https://Artist.Bandcamp.com/Track/X?Q=A": ["artist.bandcamp.com", "https://artist.bandcamp.com/Track/X?Q=A"],
    "https://artist.bandcamp.COM/": ["artist.bandcamp.com", "https://artist.bandcamp.com/"],
    "https://MUSIC.Example.Com:443/Album": ["music.example.com", "https://music.example.com:443/Album"],
}
BAD_VALUES = [0, 7, True, [], ["https://artist.bandcamp.com/"], {"u": 1}, 1.5]


def _populate(dns):
    for host, addrs in BC_BAD_RESOLVED.items():
        if addrs is not None:
            dns.table[host] = addrs
    for host, addrs in BC_GOOD.values():
        dns.table[host] = addrs
    for host, _ in BC_NORMALISED.values():
        dns.table[host] = [PUBLIC_V4]


# --- the checks themselves ---------------------------------------------------------

@pytest.mark.parametrize("url", SC_BAD)
def test_soundcloud_check_rejects(url):
    with pytest.raises(ValueError):
        check_soundcloud_url(url, "soundcloud_track_url")


@pytest.mark.parametrize("url", SC_GOOD)
def test_soundcloud_check_accepts(url):
    assert check_soundcloud_url(url, "soundcloud_track_url") == url


@pytest.mark.parametrize("url", BC_BAD_STATIC)
def test_bandcamp_check_rejects_before_any_lookup(dns, url):
    _populate(dns)
    with pytest.raises(ValueError):
        check_bandcamp_url(url, "bandcamp_track_url")
    assert dns.calls == []


@pytest.mark.parametrize("url", BC_BAD_RESOLVED_URLS)
def test_bandcamp_check_rejects_unresolvable_or_non_global(dns, url):
    _populate(dns)
    with pytest.raises(ValueError):
        check_bandcamp_url(url, "bandcamp_track_url")


@pytest.mark.parametrize("url", list(BC_GOOD))
def test_bandcamp_check_accepts(dns, url):
    _populate(dns)
    assert check_bandcamp_url(url, "bandcamp_track_url") == url
    assert dns.calls == [BC_GOOD[url][0]]


def test_bandcamp_check_looks_up_every_host_even_on_bandcamp_com(dns):
    dns.table["artist.bandcamp.com"] = ["10.0.0.1"]
    with pytest.raises(ValueError):
        check_bandcamp_url("https://artist.bandcamp.com/", "bandcamp_track_url")


@pytest.mark.parametrize("check", [check_soundcloud_url, check_bandcamp_url])
@pytest.mark.parametrize("value", BAD_VALUES + [None, b"https://soundcloud.com/x"])
def test_check_rejects_non_strings(check, value):
    with pytest.raises(ValueError):
        check(value, "k")


def test_error_names_the_key():
    with pytest.raises(ValueError, match="soundcloud_artist_url"):
        check_soundcloud_url("http://x/", "soundcloud_artist_url")
    with pytest.raises(ValueError, match="bandcamp_album_url"):
        check_bandcamp_url("http://x/", "bandcamp_album_url")


@pytest.mark.parametrize("extra", [{}, {"bandcamp_track_url": None}, {"soundcloud_track_url": ""},
                                   {k: None for k in SC_KEYS + BC_KEYS},
                                   {k: "" for k in SC_KEYS + BC_KEYS}, {"title": "http://127.0.0.1/"}])
def test_absent_keys_pass(extra):
    check_fetched_urls(extra)


def test_fetchable_url_returns_none_for_refused_and_absent(dns):
    dns.table["artist.bandcamp.com"] = [PUBLIC_V4]
    ok = "https://artist.bandcamp.com/"
    assert fetchable_url({"bandcamp_track_url": ok}, "bandcamp_track_url") == ok
    assert fetchable_url({"bandcamp_track_url": "http://127.0.0.1/"}, "bandcamp_track_url") is None
    assert fetchable_url({"bandcamp_track_url": 7}, "bandcamp_track_url") is None
    assert fetchable_url({"bandcamp_track_url": ""}, "bandcamp_track_url") is None
    assert fetchable_url({}, "soundcloud_track_url") is None


# --- recorders for the libraries ---------------------------------------------------

class _Calls:
    def __init__(self):
        self.urls = []


@pytest.fixture
def libs(monkeypatch):
    """Replace the Bandcamp classes and SoundCloud client; return what they were asked for."""
    import py_bandcamp

    calls = _Calls()

    def make(label, **fields):
        class Fake:
            @classmethod
            def from_url(cls, url):
                calls.urls.append((label, url))
                return types.SimpleNamespace(**fields)
        return Fake

    monkeypatch.setattr(py_bandcamp, "BandcampTrack", make("track", track_id=1, band_id=2, album_id=3))
    monkeypatch.setattr(py_bandcamp, "BandcampAlbum", make("album", album_id=3, band_id=2))
    monkeypatch.setattr(py_bandcamp, "BandcampArtist", make("artist", band_id=2))

    class SC:
        def resolve_user(self, url):
            calls.urls.append(("user", url))
            return {"user_id": 9}

        def resolve_track(self, url):
            calls.urls.append(("track", url))
            return {"track_id": 8, "user_id": 9}

    bandcamp, soundcloud = BandcampProvider(), SoundCloudProvider()
    bandcamp._available = True
    soundcloud._client, soundcloud._available = SC(), True
    monkeypatch.setattr(resolve_base, "active_providers",
                        lambda medium=None: [bandcamp, soundcloud])
    calls.bandcamp, calls.soundcloud = bandcamp, soundcloud
    return calls


@pytest.fixture(scope="module")
def api():
    return TestClient(create_app(ServerConfig()))


def _post(api, route, key, value):
    return api.post(route + "?refresh=true", json={"external_ids": {"extra": {key: value}}})


def _assert_refused(resp):
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == "invalid id"
    assert resp.headers["cache-control"] == "no-store"


# --- routes ------------------------------------------------------------------------

@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("key", SC_KEYS)
@pytest.mark.parametrize("url", [u for u in SC_BAD if u])
def test_route_refuses_soundcloud_url_and_never_fetches(libs, api, route, key, url):
    _assert_refused(_post(api, route, key, url))
    assert libs.urls == []


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("key", BC_KEYS)
@pytest.mark.parametrize("url", [u for u in BC_BAD_STATIC if u] + BC_BAD_RESOLVED_URLS)
def test_route_refuses_bandcamp_url_and_never_fetches(libs, dns, api, route, key, url):
    _populate(dns)
    _assert_refused(_post(api, route, key, url))
    assert libs.urls == []


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("key", SC_KEYS + BC_KEYS)
@pytest.mark.parametrize("value", BAD_VALUES)
def test_route_refuses_non_string_values(libs, api, route, key, value):
    _assert_refused(_post(api, route, key, value))
    assert libs.urls == []


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("key", SC_KEYS + BC_KEYS)
def test_route_refuses_a_bad_url_even_with_a_numeric_id_given(libs, api, route, key):
    resp = api.post(route + "?refresh=true", json={"external_ids": {"extra": {
        key: "http://127.0.0.1/x", "soundcloud_user_id": "1", "bandcamp_band_id": "1"}}})
    _assert_refused(resp)
    assert libs.urls == []


@pytest.mark.parametrize("route", ROUTES)
def test_route_refuses_when_one_of_several_keys_is_bad(libs, dns, api, route):
    dns.table["artist.bandcamp.com"] = [PUBLIC_V4]
    resp = api.post(route + "?refresh=true", json={"external_ids": {"extra": {
        "bandcamp_track_url": "https://artist.bandcamp.com/track/x",
        "soundcloud_track_url": "https://soundcloud.com/a/b",
        "soundcloud_artist_url": "https://169.254.169.254/latest"}}})
    _assert_refused(resp)
    assert libs.urls == []


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("key", SC_KEYS)
@pytest.mark.parametrize("url", SC_GOOD)
def test_route_forwards_good_soundcloud_url(libs, api, route, key, url):
    resp = _post(api, route, key, url)
    assert resp.status_code == 200, resp.text
    assert libs.urls == [("user" if key == "soundcloud_artist_url" else "track", url)]
    assert resp.json()["extra"]["soundcloud_user_id"] == "9"


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("key", BC_KEYS)
@pytest.mark.parametrize("url", list(BC_GOOD))
def test_route_forwards_good_bandcamp_url(libs, dns, api, route, key, url):
    _populate(dns)
    resp = _post(api, route, key, url)
    assert resp.status_code == 200, resp.text
    assert libs.urls == [(key.split("_")[1], url)]
    assert resp.json()["extra"]["bandcamp_band_id"] == "2"


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("key", SC_KEYS + BC_KEYS)
@pytest.mark.parametrize("value", ["", None])
def test_route_ignores_empty_and_null(libs, dns, api, route, key, value):
    resp = _post(api, route, key, value)
    assert resp.status_code == 200, resp.text
    assert libs.urls == []
    assert dns.calls == []


# --- providers, without the route --------------------------------------------------

@pytest.mark.parametrize("key", SC_KEYS)
@pytest.mark.parametrize("url", [u for u in SC_BAD if u] + BAD_VALUES)
def test_soundcloud_provider_refuses_without_the_route(libs, key, url):
    assert libs.soundcloud.enrich(ExternalIds(extra={key: url})) is None
    assert libs.urls == []


@pytest.mark.parametrize("key", BC_KEYS)
@pytest.mark.parametrize("url", [u for u in BC_BAD_STATIC if u] + BC_BAD_RESOLVED_URLS + BAD_VALUES)
def test_bandcamp_provider_refuses_without_the_route(libs, dns, key, url):
    _populate(dns)
    assert libs.bandcamp.enrich(ExternalIds(extra={key: url})) is None
    assert libs.urls == []


def test_providers_still_fetch_the_good_urls(libs, dns):
    dns.table["artist.bandcamp.com"] = [PUBLIC_V4]
    out = libs.bandcamp.enrich(ExternalIds(extra={
        "bandcamp_artist_url": "https://artist.bandcamp.com/",
        "bandcamp_track_url": "https://artist.bandcamp.com/track/x",
        "bandcamp_album_url": "https://artist.bandcamp.com/album/y"}))
    assert out.extra["bandcamp_track_id"] == "1"
    assert [label for label, _ in libs.urls] == ["artist", "track", "album"]
    out = libs.soundcloud.enrich(ExternalIds(extra={
        "soundcloud_artist_url": "https://soundcloud.com/a",
        "soundcloud_track_url": "https://on.soundcloud.com/b"}))
    assert out.extra["soundcloud_track_id"] == "8"


def test_one_bad_key_does_not_stop_the_good_one(libs, dns):
    dns.table["artist.bandcamp.com"] = [PUBLIC_V4]
    out = libs.bandcamp.enrich(ExternalIds(extra={
        "bandcamp_artist_url": "http://127.0.0.1/",
        "bandcamp_track_url": "https://artist.bandcamp.com/track/x"}))
    assert out.extra["bandcamp_track_id"] == "1"
    assert libs.urls == [("track", "https://artist.bandcamp.com/track/x")]


# --- the real libraries ------------------------------------------------------------

@pytest.mark.parametrize("route", ROUTES)
def test_loopback_server_receives_nothing(route, dns):
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        providers = [BandcampProvider(), SoundCloudProvider()]
        resolve_base_active = resolve_base.active_providers
        resolve_base.active_providers = lambda medium=None: providers
        try:
            api = TestClient(create_app(ServerConfig()))
            for key in SC_KEYS + BC_KEYS:
                for url in (f"http://127.0.0.1:{port}/{key}", f"https://127.0.0.1:{port}/{key}",
                            f"http://localhost:{port}/{key}"):
                    _assert_refused(_post(api, route, key, url))
            for provider in providers:
                keys = SC_KEYS if provider.name == "soundcloud" else BC_KEYS
                extra = {k: f"http://127.0.0.1:{port}/{k}" for k in keys}
                assert provider.enrich(ExternalIds(extra=extra)) is None
        finally:
            resolve_base.active_providers = resolve_base_active
    finally:
        server.shutdown()
        server.server_close()
    assert hits == []


# --- host case ---------------------------------------------------------------------

@pytest.mark.parametrize("url", list(SC_NORMALISED))
def test_soundcloud_check_lowercases_only_the_host(url):
    assert check_soundcloud_url(url, "soundcloud_track_url") == SC_NORMALISED[url]


@pytest.mark.parametrize("url", list(BC_NORMALISED))
def test_bandcamp_check_lowercases_only_the_host(dns, url):
    _populate(dns)
    assert check_bandcamp_url(url, "bandcamp_track_url") == BC_NORMALISED[url][1]
    assert dns.calls == [BC_NORMALISED[url][0]]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("key", SC_KEYS + BC_KEYS)
def test_route_accepts_mixed_case_host_and_hands_the_library_the_normalised_url(libs, dns, api, route, key):
    _populate(dns)
    url, expect = (("https://ON.SoundCloud.com/AbC", "https://on.soundcloud.com/AbC")
                   if key in SC_KEYS else
                   ("https://Artist.Bandcamp.com/Track/X", "https://artist.bandcamp.com/Track/X"))
    dns.table["artist.bandcamp.com"] = [PUBLIC_V4]
    resp = _post(api, route, key, url)
    assert resp.status_code == 200, resp.text
    assert [u for _, u in libs.urls] == [expect]
