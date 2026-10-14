# SPDX-License-Identifier: Apache-2.0
"""Server settings: API keys, exempt networks, rate limit, audio roots.

Every setting is off by default, so a bare ``metadatarr serve`` behaves as an
open single-tenant homelab service. :meth:`ServerConfig.from_env` reads the
``METADATARR_*`` variables documented in ``docs/deploy.md``.
"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from typing import List, Mapping, Optional, Tuple, Union

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

# Expansion of the ``private`` keyword in ``METADATARR_AUTH_EXEMPT``: loopback,
# RFC 1918, carrier-grade NAT (Tailscale), IPv6 unique-local and link-local.
PRIVATE_NETWORKS: Tuple[str, ...] = (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "100.64.0.0/10", "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10",
)

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def parse_networks(spec: str) -> List[IPNetwork]:
    """Parse a comma-separated list of CIDRs; ``private`` expands to
    :data:`PRIVATE_NETWORKS`. Raises ``ValueError`` on a malformed entry."""
    out: List[IPNetwork] = []
    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue
        if item.lower() == "private":
            out.extend(ipaddress.ip_network(n) for n in PRIVATE_NETWORKS)
        else:
            out.append(ipaddress.ip_network(item, strict=False))
    return out


@dataclass
class ServerConfig:
    """Runtime settings for :func:`metadatarr.server.app.create_app`.

    ``api_keys``: accepted keys; empty disables authentication.
    ``exempt_networks``: client networks that need no key and are not rate
    limited. The client address is the TCP peer, so behind a reverse proxy
    every request comes from the proxy's address.
    ``rate_limit_per_minute``: sustained requests per minute per key (or per
    client address when authentication is off); ``0`` disables limiting.
    ``rate_limit_burst``: bucket size; defaults to the per-minute rate.
    ``audio_roots``: directories ``/identify/audio?path=`` may read from;
    empty disables path lookups, leaving only uploads.
    """

    api_keys: List[str] = field(default_factory=list)
    exempt_networks: List[IPNetwork] = field(default_factory=list)
    rate_limit_per_minute: float = 0.0
    rate_limit_burst: Optional[int] = None
    audio_roots: List[str] = field(default_factory=list)
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)

    @property
    def burst(self) -> int:
        if self.rate_limit_burst is not None:
            return max(1, self.rate_limit_burst)
        return max(1, int(self.rate_limit_per_minute))

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "ServerConfig":
        env = os.environ if env is None else env
        keys = [k.strip() for k in env.get("METADATARR_API_KEYS", "").split(",") if k.strip()]
        roots = [r for r in env.get("METADATARR_AUDIO_ROOTS", "").split(os.pathsep) if r.strip()]
        burst_raw = env.get("METADATARR_RATE_LIMIT_BURST", "").strip()
        return cls(
            api_keys=keys,
            exempt_networks=parse_networks(env.get("METADATARR_AUTH_EXEMPT", "")),
            rate_limit_per_minute=float(env.get("METADATARR_RATE_LIMIT", "0") or 0),
            rate_limit_burst=int(burst_raw) if burst_raw else None,
            audio_roots=roots,
            max_upload_bytes=int(env.get("METADATARR_MAX_UPLOAD_BYTES", "")
                                 or DEFAULT_MAX_UPLOAD_BYTES),
        )
