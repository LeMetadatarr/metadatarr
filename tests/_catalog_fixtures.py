# SPDX-License-Identifier: Apache-2.0
"""Offline transport for the catalogue sources.

:class:`Replay` stands in for :func:`metadatarr.catalog._http.send`: each
request is answered from a recorded response under ``tests/fixtures/catalog``
(trimmed copies of real answers) or from an inline payload. A request with no
route answers 599 and is recorded in ``unrouted``, so a test notices a call it
did not expect instead of reaching the network."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlencode

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"

Answer = Union[Tuple[int, Any], Callable[..., Tuple[int, Any]]]


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str) -> Any:
    return json.loads(fixture(name))


def key(method: str, url: str, params: Optional[Dict[str, Any]] = None) -> str:
    params = {k: v for k, v in (params or {}).items() if k != "api_key"}
    query = urlencode(sorted(params.items()), doseq=True)
    return f"{method.upper()} {url}" + (f"?{query}" if query else "")


class Replay:
    def __init__(self, routes: Optional[Dict[str, Answer]] = None) -> None:
        self.routes: Dict[str, Answer] = dict(routes or {})
        self.calls: List[str] = []
        self.unrouted: List[str] = []
        self.params: List[Dict[str, Any]] = []
        self.bodies: List[Any] = []

    def add(self, method: str, url: str, answer: Answer, params: Optional[Dict[str, Any]] = None) -> "Replay":
        self.routes[key(method, url, params)] = answer
        return self

    def __call__(self, method, url, *, params=None, json_body=None, headers=None, timeout=10.0, limit=None):
        k = key(method, url, params)
        self.calls.append(k)
        self.params.append(dict(params or {}))
        self.bodies.append(json_body)
        answer = self.routes.get(k)
        if answer is None and method.upper() == "POST":
            answer = self.routes.get(f"POST {url}")
        if answer is None:
            self.unrouted.append(k)
            return 599, b"no route", {}
        if callable(answer):
            answer = answer(method=method, url=url, params=params, json_body=json_body, timeout=timeout)
        status, body, *rest = answer
        response_headers = rest[0] if rest else {}
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        return status, body[:limit] if limit else body, response_headers


def ok(name_or_payload: Any) -> Tuple[int, Any]:
    """A 200 answer from a fixture file name or an inline payload."""
    if isinstance(name_or_payload, str) and (FIXTURES / name_or_payload).exists():
        return 200, fixture(name_or_payload)
    return 200, name_or_payload


def slow(seconds: float, answer: Tuple[int, Any]) -> Callable[..., Tuple[int, Any]]:
    def run(**_kwargs):
        time.sleep(seconds)
        return answer
    return run


def boom(message: str = "connection reset") -> Callable[..., Tuple[int, Any]]:
    def run(**_kwargs):
        raise ConnectionError(message)
    return run
