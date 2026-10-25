"""Serve the built frontend from the web app (single-page app fallback)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# Paths the API and live sockets own; never answered with index.html.
API_PREFIXES = ("api", "ws", "notebook", "tensorboard", "terminal")


def mount(app: FastAPI, path: str) -> None:
    """Serve files under path, and index.html for any other non-API path, so
    the frontend's own routes load on refresh. Add it after every API route."""
    root = Path(path).resolve()
    index = root / "index.html"

    @app.get("/{rest:path}", include_in_schema=False)
    def frontend(rest: str) -> FileResponse:
        if rest.split("/", 1)[0] in API_PREFIXES:
            raise HTTPException(404)
        target = (root / rest).resolve()
        if rest and target.is_file() and target.is_relative_to(root):
            return FileResponse(target)
        return FileResponse(index)
