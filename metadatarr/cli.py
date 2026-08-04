# SPDX-License-Identifier: Apache-2.0
"""Command-line interface for metadatarr.

Currently exposes a single ``serve`` subcommand that runs the HTTP server
(JSON API + WebUI). Requires the ``server`` extra::

    pip install "metadatarr[server]"
    metadatarr serve --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from metadatarr.version import __version__


def cmd_serve(args: argparse.Namespace) -> int:
    from metadatarr.server.app import run

    try:
        run(host=args.host, port=args.port)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metadatarr",
        description="Cross-source media metadata resolver.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run the HTTP server (FastAPI) — JSON API + WebUI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
