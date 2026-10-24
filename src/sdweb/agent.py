"""AgentClient: the web app's only way to reach deck-agent (its Unix socket)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

import httpx


class AgentCallError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _error(r: httpx.Response) -> AgentCallError:
    try:
        err = r.json()["error"]
        return AgentCallError(err["code"], err["message"], r.status_code)
    except (ValueError, KeyError, TypeError):
        return AgentCallError("agent_error", "deck-agent sent an unexpected reply.",
                              r.status_code)


class AgentClient:
    def __init__(self, socket_path: str, timeout: float = 30) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.HTTPTransport(uds=self.socket_path),
                            base_url="http://deck-agent", timeout=self.timeout)

    @staticmethod
    def _headers(session: str | None, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if session:
            headers["X-SD-Session"] = session
        return headers

    def call(self, verb: str, payload: dict[str, Any] | None = None, *,
             session: str | None = None) -> Any:
        try:
            with self._client() as c:
                r = c.post(f"/v1/{verb}", json=payload or {}, headers=self._headers(session))
        except httpx.TransportError as e:
            raise AgentCallError("agent_unavailable", f"deck-agent is not reachable: {e}",
                                 503) from None
        if r.status_code != 200:
            raise _error(r)
        return r.json()["data"]

    def stream(self, verb: str, payload: dict[str, Any] | None = None, *,
               session: str | None = None) -> Iterator[bytes]:
        """A streaming verb's body, piece by piece."""
        with self._client() as c, c.stream("POST", f"/v1/{verb}", json=payload or {},
                                           headers=self._headers(session)) as r:
            if r.status_code != 200:
                r.read()
                raise _error(r)
            yield from r.iter_bytes()

    def upload_chunk(self, upload_id: str, offset: int, data: Iterable[bytes], *, length: int,
                     grant: str) -> int:
        """Stream one upload chunk (length bytes) to fs.write_chunk; the new offset."""
        headers = {"X-SD-Grant": grant, "X-SD-Upload": upload_id, "X-SD-Offset": str(offset),
                   "Content-Length": str(length), "Content-Type": "application/octet-stream"}
        with self._client() as c:
            r = c.post("/v1/fs.write_chunk", content=iter(data), headers=headers)
        if r.status_code != 200:
            raise _error(r)
        return int(r.json()["data"]["offset"])
