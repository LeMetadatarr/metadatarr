# SPDX-License-Identifier: Apache-2.0
"""FastAPI app factory + uvicorn entry point."""
from __future__ import annotations

import logging
from pathlib import Path

LOG = logging.getLogger("metadatarr.server.app")


def _require_fastapi():
    try:
        import fastapi  # noqa: F401
        import jinja2  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "fastapi + uvicorn + jinja2 are required for the server — "
            "install with `pip install metadatarr[server]`"
        ) from e


def create_app():
    """Build the metadatarr FastAPI app: JSON API + WebUI + static assets."""
    _require_fastapi()
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    from metadatarr.server.routes import register_routes
    from metadatarr.server.web import register_web

    here = Path(__file__).parent
    static_dir = here / "static"
    templates_dir = here / "templates"

    app = FastAPI(
        title="metadatarr",
        description="Cross-source media metadata resolver — HTTP surface.",
    )
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    templates = Jinja2Templates(directory=str(templates_dir))

    register_routes(app, templates)
    register_web(app, templates)
    return app


def run(*, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Block on uvicorn serving the metadatarr app."""
    _require_fastapi()
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")
