# SPDX-License-Identifier: Apache-2.0
"""Routing, failure isolation, timeouts and the cache of the catalogue
dispatcher, with fake sources standing in for real catalogues."""
from __future__ import annotations

import threading
import time

import pytest

from metadatarr import catalog
from metadatarr.catalog import base
from metadatarr.catalog.roles import is_standard_role, normalise_role
from metadatarr.catalog.shapes import Credit, Item, Person, merge_credits
from metadatarr.transport import cache_bypassed


class Fake(base.CatalogSource):
    lookup_kinds = {"movie": ("tmdb",)}
    credits_kinds = {"movie": ("tmdb",)}
    person_schemes = ("tmdb",)

    def __init__(self, name, priority=50, answer="item", delay=0.0, error=None, available=True):
        self.name, self.priority = name, priority
        self.answer, self.delay, self.error, self.is_up = answer, delay, error, available
        self.calls, self.bypass = 0, []

    def available(self):
        return self.is_up

    def _reply(self):
        self.calls += 1
        self.bypass.append(cache_bypassed())
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.answer

    def lookup(self, scheme, value, kind, *, children, timeout):
        reply = self._reply()
        return Item(kind=kind, title=f"{self.name}:{value}") if reply == "item" else reply

    def credits(self, scheme, value, kind, *, timeout):
        reply = self._reply()
        return [Credit(person=Person(name=self.name), role="actor")] if reply == "item" else reply


@pytest.fixture
def sources(monkeypatch):
    registry = {}
    monkeypatch.setattr(base, "_SOURCES", registry)
    monkeypatch.delenv("METADATARR_CATALOG_CACHE_TTL", raising=False)
    monkeypatch.delenv("METADATARR_CATALOG_CACHE_SIZE", raising=False)
    monkeypatch.setenv("METADATARR_CATALOG_TIMEOUT", "0.5")
    catalog.reset_cache()

    def add(*fakes):
        for f in fakes:
            registry[f.name] = f
        return fakes if len(fakes) > 1 else fakes[0]
    yield add
    catalog.reset_cache()


def test_no_capable_source_is_not_supported(sources):
    sources(Fake("a"))
    with pytest.raises(catalog.NotSupported):
        catalog.ask("lookup", "tvdb", "1", "series")
    with pytest.raises(catalog.NotSupported):
        catalog.ask("lookup", "tmdb", "1/1", "season")


def test_unavailable_source_is_not_supported_and_named(sources):
    sources(Fake("a", available=False))
    with pytest.raises(catalog.NotSupported, match="unavailable: a"):
        catalog.ask("lookup", "tmdb", "1", "movie")


def test_named_provider_that_cannot_answer_carries_its_name(sources):
    sources(Fake("a"))
    with pytest.raises(catalog.NotSupported) as e:
        catalog.ask("lookup", "tvdb", "1", "series", provider="a")
    assert e.value.provider == "a"


def test_priority_order_and_first_answer_wins(sources):
    low, high = sources(Fake("low", priority=90), Fake("high", priority=10))
    answer = catalog.ask("lookup", "tmdb", "7", "movie")
    assert answer.value.title == "high:7" and answer.providers == ["high"] and answer.asked == ["high"]
    assert low.calls == 0


def test_a_failing_source_is_listed_and_the_next_one_answers(sources):
    broken, good = sources(Fake("broken", priority=1, error=RuntimeError("upstream 500")), Fake("good", priority=2))
    answer = catalog.ask("lookup", "tmdb", "7", "movie")
    assert answer.value.title == "good:7"
    assert answer.providers == ["good"] and answer.asked == ["broken", "good"]
    assert [(e.provider, e.stage, e.error_type, e.message) for e in answer.errors] == [
        ("broken", "lookup", "RuntimeError", "upstream 500")]


def test_a_slow_source_times_out_and_does_not_hold_the_answer(sources):
    sources(Fake("slow", priority=1, delay=3.0), Fake("fast", priority=2))
    started = time.monotonic()
    answer = catalog.ask("lookup", "tmdb", "7", "movie")
    elapsed = time.monotonic() - started
    assert answer.value.title == "fast:7"
    assert [e.error_type for e in answer.errors] == ["TimeoutError"]
    assert elapsed < 2.0, elapsed


def test_not_found_everywhere_is_none_without_errors(sources):
    sources(Fake("a", answer=None), Fake("b", answer=None, priority=60))
    answer = catalog.ask("lookup", "tmdb", "7", "movie")
    assert answer.value is None and answer.errors == [] and answer.asked == ["a", "b"]


def test_empty_credits_are_an_answer_not_a_miss(sources):
    a, b = sources(Fake("a", answer=[]), Fake("b", priority=60))
    answer = catalog.ask("credits", "tmdb", "7", "movie")
    assert answer.value == [] and answer.providers == ["a"] and b.calls == 0


def test_answers_are_cached_and_refresh_asks_again(sources):
    a = sources(Fake("a"))
    catalog.ask("lookup", "tmdb", "7", "movie")
    catalog.ask("lookup", "tmdb", "7", "movie")
    assert a.calls == 1
    catalog.ask("lookup", "tmdb", "7", "movie", refresh=True)
    assert a.calls == 2 and a.bypass == [False, True]
    catalog.ask("lookup", "tmdb", "7", "movie")
    assert a.calls == 2


def test_cache_keys_include_kind_children_and_provider(sources):
    a = sources(Fake("a"))
    catalog.ask("lookup", "tmdb", "7", "movie")
    catalog.ask("lookup", "tmdb", "7", "movie", children=False)
    catalog.ask("lookup", "tmdb", "7", "movie", provider="a")
    catalog.ask("lookup", "tmdb", "8", "movie")
    assert a.calls == 4


def test_misses_failures_and_degraded_answers_are_not_cached(sources):
    a = sources(Fake("a", answer=None))
    catalog.ask("lookup", "tmdb", "7", "movie")
    catalog.ask("lookup", "tmdb", "7", "movie")
    assert a.calls == 2
    a.answer, a.error = "item", RuntimeError("down")
    b = sources(Fake("b", priority=60))
    catalog.ask("lookup", "tmdb", "7", "movie")
    catalog.ask("lookup", "tmdb", "7", "movie")
    assert b.calls == 2, "an answer given while a better source failed must not be kept"


def test_cache_is_bounded_and_expires(monkeypatch):
    now = [0.0]
    cache = base.TTLCache(ttl=10, max_entries=2, clock=lambda: now[0])
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") == (False, None) and cache.get("c") == (True, 3) and len(cache) == 2
    now[0] = 11
    assert cache.get("c") == (False, None)


def test_cache_size_zero_disables_it(sources, monkeypatch):
    monkeypatch.setenv("METADATARR_CATALOG_CACHE_SIZE", "0")
    catalog.reset_cache()
    a = sources(Fake("a"))
    catalog.ask("lookup", "tmdb", "7", "movie")
    catalog.ask("lookup", "tmdb", "7", "movie")
    assert a.calls == 2


def test_malformed_questions_are_value_errors(sources):
    sources(Fake("a"))
    for args in (("lookup", "tmdb", "", "movie"), ("lookup", "", "7", "movie"), ("lookup", "tmdb", "7", "spaceship"),
                 ("lookup", "tmdb", "x" * 201, "movie"), ("lookup", "nosuchscheme", "7", None), ("hug", "tmdb", "7", None)):
        with pytest.raises(ValueError):
            catalog.ask(*args)


def test_default_kind_follows_the_scheme(sources):
    sources(Fake("a"))
    assert catalog.ask("lookup", "tmdb", "7").value.kind == "movie"
    assert base.default_kind("openlibrary", "OL1A") == "author"
    assert base.default_kind("openlibrary", "OL1W") == "book"


def test_error_messages_do_not_carry_credentials(sources):
    sources(Fake("a", error=ConnectionError("Max retries exceeded with url: /3/movie/1?api_key=SECRET123&x=1")))
    answer = catalog.ask("lookup", "tmdb", "1", "movie")
    assert "SECRET123" not in answer.errors[0].message and "api_key=***" in answer.errors[0].message


def test_concurrent_askers_share_one_cache_safely(sources):
    sources(Fake("a", delay=0.01))
    results = []

    def run(i):
        results.append(catalog.ask("lookup", "tmdb", str(i % 5 + 1), "movie").value.title)
    threads = [threading.Thread(target=run, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(set(results)) == [f"a:{i}" for i in range(1, 6)] and len(results) == 40


# -- roles ---------------------------------------------------------------------------

@pytest.mark.parametrize("word,role", [
    ("Voice", "voice-actor"), ("Original Music Composer", "composer"), ("Director of Photography", "cinematographer"),
    ("Screenplay", "screenwriter"), ("Series Composition", "writer"), ("Original Creator", "adapted-from"),
    ("Theme Song Performance (OP)", "performer"), ("design/illustration", "cover-artist"),
    ("Co-Executive Producer", "executive-producer"), ("narrated_by", "narrator"), ("label", "label"),
    ("Voice Director", "audio-director"), ("Dub Director", "audio-director"), ("Voice Actor (Japanese)", "voice-actor"),
    ("ADR Voice Casting", "casting"), ("Voice Casting", "casting"), ("Casting Director", "casting"),
    ("Voice Recording", "voice-recording"), ("Voice Supervisor", "voice-supervisor"), ("", ""), (None, ""),
])
def test_normalise_role(word, role):
    assert normalise_role(word) == role


def test_unknown_words_pass_through_as_roles_of_their_own():
    assert normalise_role("Key Animation") == "key-animation"
    assert not is_standard_role("key-animation") and is_standard_role("voice-actor")


def test_provider_overrides_win_over_the_generic_word():
    assert normalise_role("producer") == "producer"
    assert normalise_role("producer", {"producer": "producer-music"}) == "producer-music"


def test_merge_credits_joins_notes_and_numbers_each_role():
    p = Person(name="Jonny", ext_ids={"musicbrainz": "x"})
    merged = merge_credits([Credit(person=p, role="performer", note="guitar"),
                            Credit(person=Person(name="Thom"), role="performer"),
                            Credit(person=p.model_copy(), role="performer", note="organ"),
                            Credit(person=p.model_copy(), role="writer")])
    assert [(c.person.name, c.role, c.note, c.position) for c in merged] == [
        ("Jonny", "performer", "guitar, organ", 0), ("Thom", "performer", "", 1), ("Jonny", "writer", "", 0)]


def test_voice_fallback_is_for_cast_entries_only():
    assert normalise_role("Lead Voice", cast=True) == "voice-actor"
    assert normalise_role("Lead Voice") == "lead-voice"


@pytest.mark.parametrize("scheme,value,kind", [("tmdb", "99999999999999999999", "movie"), ("tmdb", "-1", "movie"),
                                               ("tvdb", "81189/x", "season"), ("anilist", "abc", "series"),
                                               ("tmdb", "1/2", "movie")])
def test_numeric_ids_are_checked_before_any_request(sources, scheme, value, kind):
    with pytest.raises(base.InvalidId):
        catalog.ask("lookup", scheme, value, kind)


def test_a_source_can_report_a_truncated_answer(sources):
    class Paged(Fake):
        def lookup(self, scheme, value, kind, *, children, timeout):
            base.mark_truncated()
            return Item(kind=kind, title="partial")
    sources(Paged("p"))
    assert catalog.ask("lookup", "tmdb", "7", "movie").truncated is True
    assert catalog.ask("lookup", "tmdb", "7", "movie").truncated is True  # the cached answer keeps the flag
    sources(Fake("q", priority=1))
    catalog.reset_cache()
    assert catalog.ask("lookup", "tmdb", "8", "movie").truncated is False
