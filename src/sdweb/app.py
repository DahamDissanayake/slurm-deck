"""The web app: create_app(settings) builds the FastAPI application."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from sdweb import db, static
from sdweb.accounts.allowlist import router as allowlist_router
from sdweb.accounts.applications import router as applications_router
from sdweb.accounts.routes import router as accounts_router
from sdweb.agent import AgentClient
from sdweb.auth.routes import router as auth_router
from sdweb.cluster import router as cluster_router
from sdweb.config import WebSettings, load_settings
from sdweb.deps import ApiError
from sdweb.files.tus import router as uploads_router
from sdweb.jobs.routes import router as jobs_router
from sdweb.jobs.templates import router as templates_router
from sdweb.live.routes import router as live_router
from sdweb.notify.routes import router as notify_router

# Where the image puts the built frontend (deploy/web.Dockerfile).
STATIC_DIR = "/app/static"


def create_app(settings: WebSettings, agent: Any | None = None) -> FastAPI:
    """agent is the deck-agent client (sdweb.agent.AgentClient) once wired in."""
    app = FastAPI(title="Slurm Deck", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.agent = agent
    app.state.sessionmaker = sessionmaker(db.engine(settings), expire_on_commit=False)
    app.state.clock = lambda: datetime.now(UTC)

    @app.exception_handler(ApiError)
    def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": exc.code, **exc.extra}, status_code=exc.status)

    app.include_router(auth_router)
    app.include_router(accounts_router)
    app.include_router(allowlist_router)
    app.include_router(applications_router)
    for router in (cluster_router, jobs_router, templates_router, live_router,
                   notify_router, uploads_router):
        app.include_router(router)
    return app


def create_app_from_env(environ: Mapping[str, str] | None = None,
                        static_dir: str = STATIC_DIR) -> FastAPI:
    """The container's app (uvicorn --factory): settings from the environment,
    the real deck-agent client, and the built frontend when it is there."""
    settings = load_settings(os.environ if environ is None else environ)
    app = create_app(settings, agent=AgentClient(settings.agent_socket))
    if os.path.isdir(static_dir):
        static.mount(app, static_dir)
    return app
