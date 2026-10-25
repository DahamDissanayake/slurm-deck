"""The small pages the session proxy shows instead of a raw error. Plain HTML
with the app's palette (light and dark), no scripts."""

from __future__ import annotations

from html import escape

from fastapi.responses import HTMLResponse

STYLE = """
:root{--bg:#f6f7f9;--text:#1b1f24;--dim:#5b6470;--accent:#0b6bcb}
@media (prefers-color-scheme: dark){
:root{--bg:#0f1318;--text:#e6e9ee;--dim:#98a2b0;--accent:#5aa9ff}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);
color:var(--text);font:16px system-ui,sans-serif}
main{max-width:30rem;padding:1.5rem}h1{font-size:1.25rem;margin:0 0 .75rem}
p{color:var(--dim);line-height:1.5}a{color:var(--accent)}
"""


def _page(title: str, body: str, status: int, refresh: int | None = None) -> HTMLResponse:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    html = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">{meta}'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(title)}</title><style>{STYLE}</style></head><body><main>"
            f"<h1>{escape(title)}</h1>{body}</main></body></html>")
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})


def starting(home: str = "") -> HTMLResponse:
    return _page("Starting your session…", "<p>This page refreshes by itself.</p>", 200, 3)


def _back(home: str, path: str = "/jobs", label: str = "Back to your jobs") -> str:
    """A link into the app; absolute (home) when the page is on the session origin."""
    return f'<p><a href="{escape(home + path, quote=True)}">{escape(label)}</a></p>'


def ended(home: str = "") -> HTMLResponse:
    return _page("This session has ended.", _back(home), 200)


def forbidden(home: str = "") -> HTMLResponse:
    return _page("This session belongs to someone else.", _back(home), 403)


def not_found(home: str = "") -> HTMLResponse:
    return _page("There is no such session.", _back(home), 404)


def not_responding(job_id: str, home: str = "") -> HTMLResponse:
    return _page("The session isn't responding. It may still be starting, or it has stopped.",
                 _back(home, f"/jobs/{job_id}", "See the job and its log"), 502)


def reopen(home: str) -> HTMLResponse:
    """The session origin without a live ticket, for a request that can't just
    be redirected (anything but a GET)."""
    return _page("Open this session from Slurm Deck again.", _back(home), 403)


def bad_link(home: str) -> HTMLResponse:
    return _page("This link doesn't open a session.", _back(home), 400)
