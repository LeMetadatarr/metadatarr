"""Wiktionary drug name pronunciation scraper.

Crawls the Wiktionary 'en:Pharmaceutical drugs' category and extracts IPA
transcriptions for each drug name across 12 language editions: en, es, fr,
pt, de, it, ru, tr, ar, zh, ja, ko.

Schema per row:
  term, language, ipa[], wikitext_excerpt, wiktionary_url, source_wiktionary

Two-phase crawl: (1) drain the English category listing via MediaWiki
``cmcontinue`` pagination to build the full title list, then build a
``(title, lang)`` work queue (English first, then all 12 editions per
title); (2) pop off the queue in batches, fetching+parsing each page. Neither
phase is offset/skip pagination, so :meth:`fetch` is overridden directly —
one category page per call in phase 1, up to 100 ``(title, lang)`` lookups
per call in phase 2 (mirroring the original's batch-of-100 write cadence).
The cursor is ``{"stage": "cat", "cat_cont": ..., "en_titles": [...]}`` or
``{"stage": "process", "queue": [[title, lang], ...]}``.

NOTE — deviation: the original has no row-level dedup (each ``(title, lang)``
pair is fetched exactly once purely because the queue is consumed once, not
because of a content-based ``seen`` id — the same ``term`` legitimately
recurs once per language). This port sets ``id_field = ""`` to match.

Run it::

    python -m metadatarr.scrapers wiktionary_pronunciations [--output DIR] [--delay SECS]
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

# Wiktionary MediaWiki API endpoints per language edition
WIKIS = {
    "en": "https://en.wiktionary.org/w/api.php",
    "es": "https://es.wiktionary.org/w/api.php",
    "fr": "https://fr.wiktionary.org/w/api.php",
    "pt": "https://pt.wiktionary.org/w/api.php",
    "de": "https://de.wiktionary.org/w/api.php",
    "it": "https://it.wiktionary.org/w/api.php",
    "ru": "https://ru.wiktionary.org/w/api.php",
    "tr": "https://tr.wiktionary.org/w/api.php",
    "ar": "https://ar.wiktionary.org/w/api.php",
    "zh": "https://zh.wiktionary.org/w/api.php",
    "ja": "https://ja.wiktionary.org/w/api.php",
    "ko": "https://ko.wiktionary.org/w/api.php",
}
_OTHER_LANGS = ("es", "fr", "pt", "de", "it", "ru", "tr", "ar", "zh", "ja", "ko")

EN_PHARMA_CAT = "Category:en:Pharmaceutical drugs"
PAGE_LIMIT = 500
PROCESS_BATCH = 100


def _extract_ipa(wikitext: str) -> List[str]:
    """Extract IPA transcriptions from wikitext."""
    ipa_set: list = []
    for m in re.finditer(r'\{\{IPA[^}]*?/([^/|}]+)/[^}]*\}\}', wikitext):
        val = m.group(1).strip()
        if val and val not in ipa_set:
            ipa_set.append(val)
    if not ipa_set:
        pron = re.search(r'==\s*Pronunciation\s*==\n(.*?)(?:==|\Z)', wikitext, re.S)
        if pron:
            for m in re.finditer(r'/([^/\n]{2,40})/', pron.group(1)):
                val = m.group(1).strip()
                if val not in ipa_set:
                    ipa_set.append(val)
    return ipa_set


@register
class WiktionaryPronunciationsSource(PaginatedJSONSource):
    name = "wiktionary_pronunciations"
    id_field = ""  # original has no content-based dedup — same term recurs per language
    default_delay = 0.35

    user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    accept = "application/json"

    def session(self):
        if self._session is None:
            try:
                from unblock_requests import CloudflareSession
                s = CloudflareSession()
            except Exception:
                import requests
                s = requests.Session()
            s.headers.update({"User-Agent": self.user_agent, "Accept": self.accept})
            self._session = s
        return self._session

    def initial_cursor(self) -> Dict[str, Any]:
        return {"stage": "cat", "cat_cont": None, "en_titles": []}

    def _api_get(self, wiki_url: str, **params) -> dict:
        self.throttle.wait()
        params.setdefault("format", "json")
        r = self.session().get(wiki_url, params=params, timeout=20)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    def _list_category_members(self, continue_from: Optional[str] = None) -> Tuple[List[str], Optional[str]]:
        """Return (titles, next_continue) for one page of category members."""
        params: dict = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": EN_PHARMA_CAT,
            "cmlimit": PAGE_LIMIT,
            "cmtype": "page",
        }
        if continue_from:
            params["cmcontinue"] = continue_from
        data = self._api_get(WIKIS["en"], **params)
        members = [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        next_cont = data.get("continue", {}).get("cmcontinue")
        return members, next_cont

    def _fetch_pronunciations(self, title: str, wiki_lang: str) -> Optional[Dict[str, Any]]:
        """Fetch wikitext for a title and extract IPA. Returns row or None."""
        data = self._api_get(WIKIS[wiki_lang], action="parse", page=title, prop="wikitext")
        parse = data.get("parse", {})
        if not parse:
            return None
        wikitext = parse.get("wikitext", {}).get("*", "")
        ipa = _extract_ipa(wikitext)
        if not ipa:
            return None
        base_domain = WIKIS[wiki_lang].replace("/w/api.php", "")
        url = f"{base_domain}/wiki/{title.replace(' ', '_')}"
        return {
            "term": title,
            "language": wiki_lang,
            "ipa": ipa,
            "wikitext_excerpt": wikitext[:500].strip(),
            "wiktionary_url": url,
            "source_wiktionary": wiki_lang,
        }

    def fetch(self, cursor: Dict[str, Any]):
        stage = cursor.get("stage", "cat")

        if stage == "cat":
            cat_cont = cursor.get("cat_cont")
            en_titles: List[str] = list(cursor.get("en_titles") or [])

            titles, next_cont = self._list_category_members(cat_cont)
            en_titles.extend(titles)

            if next_cont:
                return [], {"stage": "cat", "cat_cont": next_cont, "en_titles": en_titles}

            lang_queue: List[List[str]] = [[t, "en"] for t in en_titles]
            for t in en_titles:
                for lang in _OTHER_LANGS:
                    lang_queue.append([t, lang])
            return [], {"stage": "process", "queue": lang_queue}

        if stage == "process":
            queue: List[List[str]] = list(cursor.get("queue") or [])
            if not queue:
                return [], None

            batch, remaining = queue[:PROCESS_BATCH], queue[PROCESS_BATCH:]
            rows = []
            for title, lang in batch:
                row = self._fetch_pronunciations(title, lang)
                if row:
                    rows.append(row)

            next_cursor = {"stage": "process", "queue": remaining} if remaining else None
            return rows, next_cursor

        return [], None


if __name__ == "__main__":
    raise SystemExit(run_cli(WiktionaryPronunciationsSource))
