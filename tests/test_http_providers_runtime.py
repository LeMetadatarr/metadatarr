"""HTTP resolve providers use the project transport, not an optional httpx."""
import json
import sys
from pathlib import Path

import pytest
from mediavocab import MediaType
from mediavocab.models.signals import Signals

from metadatarr.resolve.providers import anilist, jikan, librivox, podcast_index
from metadatarr.resolve.base import consolidate

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return _Resp(self.payload)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return _Resp(self.payload)


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def no_httpx(monkeypatch):
    monkeypatch.setitem(sys.modules, "httpx", None)
    with pytest.raises(ImportError):
        import httpx  # noqa: F401


def _stub(monkeypatch, module, payload):
    sess = _Session(payload)
    monkeypatch.setattr(module, "_SESSION", sess)
    return sess


def test_apple_podcasts_matches_without_httpx(monkeypatch, no_httpx):
    sess = _stub(monkeypatch, podcast_index, _fixture("itunes_lookup_536258179.json"))
    m = podcast_index.ApplePodcastsProvider().lookup(
        Signals(title="Welcome to Night Vale", medium=MediaType.PODCAST))
    assert m is not None
    assert m.external_ids.apple_podcast_id == 536258179
    assert sess.calls and sess.calls[0][1] == podcast_index._ITUNES_SEARCH


def test_librivox_matches_without_httpx(monkeypatch, no_httpx):
    sess = _stub(monkeypatch, librivox, _fixture("librivox_47.json"))
    m = librivox.LibriVoxProvider().lookup(
        Signals(title="Count of Monte Cristo", medium=MediaType.AUDIOBOOK))
    assert m is not None
    assert m.external_ids.librivox_id == 47
    assert sess.calls and sess.calls[0][1] == librivox._API


def test_jikan_requests_through_transport_without_httpx(monkeypatch, no_httpx):
    sess = _stub(monkeypatch, jikan, {"data": [
        {"mal_id": 1, "title": "Cowboy Bebop", "year": 1998}]})
    from mediavocab.taxonomy import GENRE_ANIME
    m = jikan.JikanAnimeProvider().lookup(Signals(
        title="Cowboy Bebop", medium=MediaType.EPISODIC_SERIES,
        content_genres=[GENRE_ANIME]))
    assert m is not None and m.external_ids.mal_id == 1
    assert sess.calls[0][1].endswith("/anime")


def test_anilist_requests_through_transport_without_httpx(monkeypatch, no_httpx):
    sess = _stub(monkeypatch, anilist, {"data": {"Media": {
        "id": 1, "title": {"english": "Cowboy Bebop"}, "startDate": {"year": 1998}}}})
    from mediavocab.taxonomy import GENRE_ANIME
    m = anilist.AniListProvider().lookup(Signals(
        title="Cowboy Bebop", medium=MediaType.EPISODIC_SERIES,
        content_genres=[GENRE_ANIME]))
    assert m is not None and m.external_ids.anilist_id == 1
    assert sess.calls[0][0] == "POST"


# --- wire-level behaviour: outgoing headers, host spacing, empty answers ------

import subprocess
import textwrap

import requests
import requests.adapters

from metadatarr import transport


def _wire(monkeypatch, bodies):
    """Replace the network under the adapter; returns the list of sent requests."""
    sent = []
    queue = list(bodies)

    def send(self, request, **kw):
        sent.append(request)
        body = queue.pop(0) if len(queue) > 1 else queue[0]
        r = requests.Response()
        r.status_code = 200
        r.url = request.url
        r._content = body if isinstance(body, bytes) else json.dumps(body).encode()
        r._content_consumed = True
        return r

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    return sent


def _cached_session(monkeypatch, tmp_path):
    monkeypatch.setenv("METADATARR_HTTP_CACHE", str(tmp_path))
    return transport.make_session()


def test_providers_send_the_project_user_agent(monkeypatch):
    sent = _wire(monkeypatch, [{"results": [], "books": [], "data": []}])
    from mediavocab.taxonomy import GENRE_ANIME
    for prov, sig in [
        (podcast_index.ApplePodcastsProvider(), Signals(title="x", medium=MediaType.PODCAST)),
        (librivox.LibriVoxProvider(), Signals(title="x", medium=MediaType.AUDIOBOOK)),
        (jikan.JikanAnimeProvider(), Signals(title="x", medium=MediaType.EPISODIC_SERIES,
                                             content_genres=[GENRE_ANIME])),
        (anilist.AniListProvider(), Signals(title="x", medium=MediaType.EPISODIC_SERIES,
                                            content_genres=[GENRE_ANIME])),
    ]:
        prov.lookup(sig)
    assert len(sent) >= 4
    for req in sent:
        assert req.headers["User-Agent"] == transport.USER_AGENT
        assert "python-requests" not in req.headers["User-Agent"]
        assert "@" not in req.headers["User-Agent"]


def test_resolve_anilist_shares_the_two_second_spacing(monkeypatch):
    from mediavocab.taxonomy import GENRE_ANIME
    _wire(monkeypatch, [{"data": {"Media": None}}])
    now = [100.0]
    slept = []
    lim = transport._GLOBAL_LIMITER
    monkeypatch.setattr(lim, "_time", lambda: now[0])
    monkeypatch.setattr(lim, "_sleep", lambda s: slept.append(s))
    monkeypatch.setattr(lim, "_last", {})
    sig = Signals(title="x", medium=MediaType.EPISODIC_SERIES, content_genres=[GENRE_ANIME])
    p = anilist.AniListProvider()
    p.lookup(sig)
    p.lookup(sig)
    assert slept == [pytest.approx(2.0)]


@pytest.mark.parametrize("empty", [{"results": []}, b"<html>busy</html>", b""])
def test_apple_podcasts_empty_answer_is_not_cached(monkeypatch, tmp_path, empty):
    _wire(monkeypatch, [empty, _fixture("itunes_lookup_536258179.json")])
    monkeypatch.setattr(podcast_index, "_SESSION", _cached_session(monkeypatch, tmp_path))
    sig = Signals(title="Welcome to Night Vale", medium=MediaType.PODCAST)
    p = podcast_index.ApplePodcastsProvider()
    assert p.lookup(sig) is None
    assert p.lookup(sig).external_ids.apple_podcast_id == 536258179


def test_librivox_empty_answer_is_not_cached(monkeypatch, tmp_path):
    _wire(monkeypatch, [{"books": []}, _fixture("librivox_47.json")])
    monkeypatch.setattr(librivox, "_SESSION", _cached_session(monkeypatch, tmp_path))
    sig = Signals(title="Count of Monte Cristo", medium=MediaType.AUDIOBOOK)
    p = librivox.LibriVoxProvider()
    assert p.lookup(sig) is None
    assert p.lookup(sig).external_ids.librivox_id == 47


def test_jikan_empty_answer_is_not_cached(monkeypatch, tmp_path):
    from mediavocab.taxonomy import GENRE_ANIME
    _wire(monkeypatch, [{"data": []}, {"data": [{"mal_id": 1, "title": "Cowboy Bebop"}]}])
    monkeypatch.setattr(jikan, "_SESSION", _cached_session(monkeypatch, tmp_path))
    sig = Signals(title="Cowboy Bebop", medium=MediaType.EPISODIC_SERIES,
                  content_genres=[GENRE_ANIME])
    p = jikan.JikanAnimeProvider()
    assert p.lookup(sig) is None
    assert p.lookup(sig).external_ids.mal_id == 1


def test_real_answers_stay_cached(monkeypatch, tmp_path):
    sent = _wire(monkeypatch, [_fixture("librivox_47.json")])
    monkeypatch.setattr(librivox, "_SESSION", _cached_session(monkeypatch, tmp_path))
    sig = Signals(title="Count of Monte Cristo", medium=MediaType.AUDIOBOOK)
    p = librivox.LibriVoxProvider()
    assert p.lookup(sig) and p.lookup(sig)
    assert len(sent) == 1


def test_providers_import_and_run_when_httpx_is_missing_at_import_time():
    script = textwrap.dedent("""
        import sys
        sys.modules["httpx"] = None
        from metadatarr.resolve.providers import anilist, jikan, librivox, podcast_index
        for m in (anilist, jikan, librivox, podcast_index):
            assert "httpx" not in vars(m), m
            assert m._SESSION is not None
        print("ok")
    """)
    out = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


def test_librivox_long_title_survives_consolidation(monkeypatch):
    book = {"id": "381", "title": "Frankenstein, or The Modern Prometheus",
            "language": "English", "copyright_year": "1818",
            "authors": [{"id": "783", "first_name": "Mary", "last_name": "Shelley"}]}
    _stub(monkeypatch, librivox, {"books": [book]})
    query = Signals(title="Frankenstein", medium=MediaType.AUDIOBOOK)
    m = librivox.LibriVoxProvider().lookup(query)
    result = consolidate([m], query)
    assert [a.provider for a in result.accepted] == ["librivox"]
    assert result.dropped == []
    assert result.external_ids.librivox_id == 381
