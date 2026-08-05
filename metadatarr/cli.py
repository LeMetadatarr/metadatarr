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


def cmd_tag_library(args: argparse.Namespace) -> int:
    from metadatarr.library import tag_library

    stats: dict = {}
    results = tag_library(
        args.path,
        media=args.media,
        write_nfo=not args.no_nfo,
        dry_run=args.dry_run,
        min_confidence=args.min_confidence,
        skip_extras=not args.no_skip_extras,
        rename=args.rename,
        rename_pattern=args.rename_pattern,
        rename_folder=args.rename_folder,
        stats=stats,
    )

    matched = 0
    nfo_written = 0
    errors = 0
    renamed = 0
    would_rename = 0
    rename_skipped = 0
    for r in results:
        extra = f"\t{r.rename_action}:{r.renamed_to}" if r.rename_action != "off" else ""
        print(f"{r.action}\t{r.path}\t{r.note}{extra}")
        if r.matched:
            matched += 1
        if r.action == "wrote":
            nfo_written += 1
        if r.action == "error" or r.rename_action == "error":
            errors += 1
        if r.rename_action == "renamed":
            renamed += 1
        elif r.rename_action == "would-rename":
            would_rename += 1
        elif r.rename_action in ("skipped-unmatched", "skipped-exists"):
            rename_skipped += 1

    print(
        f"scanned={len(results)} matched={matched} nfo-written={nfo_written} "
        f"skipped-extras={stats.get('skipped_extras', 0)} errors={errors} "
        f"renamed={renamed} would-rename={would_rename} rename-skipped={rename_skipped}"
    )
    return 0


def cmd_identify(args: argparse.Namespace) -> int:
    from metadatarr.identify import AudioIdentifyError, identify_audio

    try:
        match = identify_audio(args.audiofile)
    except AudioIdentifyError as e:
        print(str(e), file=sys.stderr)
        return 1

    if not match.matched:
        print("no match")
        return 0

    if args.json:
        import json

        print(json.dumps({
            "matched": match.matched,
            "title": match.title,
            "artist": match.artist,
            "album": match.album,
            "isrc": match.isrc,
            "cover_art": match.cover_art,
            "external_ids": match.external_ids.model_dump(),
        }, indent=2))
    else:
        print(f"{match.title} — {match.artist}")
        if match.album:
            print(f"album: {match.album}")
        if match.isrc:
            print(f"isrc: {match.isrc}")
        ids = match.external_ids.model_dump(exclude_defaults=True, exclude={"extra"})
        for k, v in ids.items():
            print(f"{k}: {v}")
        for k, v in match.external_ids.extra.items():
            print(f"{k}: {v}")
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

    p_tag = sub.add_parser(
        "tag-library",
        help="scan a local media library and write Kodi/Jellyfin .nfo sidecars",
    )
    p_tag.add_argument("--path", "-p", required=True, help="library root to scan")
    p_tag.add_argument("--media", choices=["both", "video", "music"], default="both")
    p_tag.add_argument("--nfo", dest="no_nfo", action="store_false",
                       help="write .nfo sidecars (default)")
    p_tag.add_argument("--no-nfo", dest="no_nfo", action="store_true",
                       help="resolve only, do not write .nfo sidecars")
    p_tag.set_defaults(no_nfo=False)
    p_tag.add_argument("--dry-run", action="store_true",
                       help="report what would be written without writing anything")
    p_tag.add_argument("--min-confidence", type=float, default=0.5)
    p_tag.add_argument("--no-skip-extras", action="store_true",
                       help="also tag trailers/samples/extras (skipped by default)")
    p_tag.add_argument("--rename", action="store_true",
                       help="DESTRUCTIVE, opt-in: also rename/organize confidently-"
                            "matched media files (and their .nfo) to a clean "
                            "'Title (Year) {tmdb-id}' convention. Off by default. "
                            "Combine with --dry-run to preview without moving "
                            "anything. Never renames an unmatched file and never "
                            "overwrites an existing file at the target path.")
    p_tag.add_argument("--rename-pattern", default=None,
                       help="optional custom rename pattern, e.g. "
                            "'{title} ({year})'; fields: title, year, id, artist, "
                            "season, episode. Defaults to a built-in Radarr/"
                            "Jellyfin-style pattern per media kind.")
    p_tag.add_argument("--rename-folder", action="store_true",
                       help="with --rename: also move the file into a "
                            "'Title (Year)/' folder (Jellyfin movie-folder "
                            "layout). Off by default (renames in place).")
    p_tag.set_defaults(func=cmd_tag_library)

    p_identify = sub.add_parser(
        "identify",
        help="identify a song from an audio file (Shazam via xazam) and resolve/enrich its metadata",
    )
    p_identify.add_argument("audiofile", help="path to an audio file (mp3/wav/etc.)")
    p_identify.add_argument("--json", action="store_true",
                            help="print the full result as JSON")
    p_identify.set_defaults(func=cmd_identify)

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
