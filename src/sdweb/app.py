"""The web app: create_app(settings) builds the FastAPI application."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from sdweb import db
from sdweb.auth.routes import router as auth_router
from sdweb.config import WebSettings
from sdweb.deps import ApiError


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
    return app
