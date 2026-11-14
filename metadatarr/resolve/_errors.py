"""Structured diagnostics for swallowed provider failures.

The resolver fans out to many providers and, by contract, a single provider
blowing up must never break a resolve — the failure is swallowed and the run
continues with whatever the other providers returned. That contract is correct,
but a silently swallowed exception hides upstream schema drift: a ``KeyError``
from a changed API response looks identical to "this provider had no match".

:class:`ProviderError` records one swallowed failure so it can surface in
:class:`~metadatarr.resolve.base.ResolveResult`, and :func:`trap` is the context
manager the fan-out uses to log, record, and suppress those failures uniformly.
"""
from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from typing import List, Optional

from pydantic import BaseModel

LOG = logging.getLogger("metadatarr.resolve")

_MAX_MESSAGE = 500


class ProviderError(BaseModel):
    """One swallowed failure from a provider during fan-out."""

    provider: str
    stage: str
    """One of ``"lookup"``, ``"candidates"``, ``"variants"``, ``"enrich"``."""
    error_type: str
    """The exception class name (``exc.__class__.__name__``)."""
    message: str
    """``str(exc)``, truncated to 500 characters."""


class trap(AbstractContextManager):
    """Context manager that traps a swallowed provider failure.

    Logs the exception at ``WARNING`` with the provider name and stage, appends
    a :class:`ProviderError` to *sink* when one is given, and suppresses the
    exception so the fan-out continues. ``KeyboardInterrupt`` and ``SystemExit``
    are never suppressed — they propagate untouched.

    ``list.append`` is atomic under the GIL, so a *sink* shared across worker
    threads needs no additional locking.
    """

    def __init__(self, provider_name: str, stage: str,
                 sink: Optional[List[ProviderError]] = None) -> None:
        self.provider_name = provider_name
        self.stage = stage
        self.sink = sink

    def __enter__(self) -> "trap":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            return False
        if not isinstance(exc, Exception):
            # BaseException-only failures (KeyboardInterrupt, SystemExit)
            # must propagate.
            return False
        LOG.warning("provider %s failed during %s: %s",
                    self.provider_name, self.stage, exc)
        if self.sink is not None:
            self.sink.append(ProviderError(
                provider=self.provider_name,
                stage=self.stage,
                error_type=exc.__class__.__name__,
                message=str(exc)[:_MAX_MESSAGE],
            ))
        return True
