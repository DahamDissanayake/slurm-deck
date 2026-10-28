"""Helpers for the acceptance scenarios; settings are listed in conftest.py."""

from __future__ import annotations

import os
import re
import secrets
import shlex
import subprocess
import time
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

import httpx
import pytest

T = TypeVar("T")
PREFIX = os.environ.get("SD_E2E_PREFIX", "sdtest")
EMAIL = os.environ.get("SD_E2E_EMAIL", "delivered+{name}@resend.dev")
PSQL = os.environ.get(
    "SD_E2E_PSQL", "sudo docker exec deploy-db-1 psql -U sdweb -d slurmdeck -At -c")
JOB_WAIT = float(os.environ.get("SD_E2E_JOB_WAIT", "1800"))
TOKEN_RE = re.compile(r"#token=([A-Za-z0-9_.~%-]+)")


def wait_for(check: Callable[[], T | None], timeout: float, what: str,
             every: float = 5.0) -> T:
    """Poll check() until it returns something truthy, or fail naming what."""
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > deadline:
            pytest.fail(f"timed out after {timeout:.0f}s waiting for {what}")
        time.sleep(every)


class PinnedTransport(httpx.HTTPTransport):
    """Connects every request to one address, keeping the hostname for SNI and
    Host, so a test machine needs no DNS or hosts entry for the site."""

    def __init__(self, address: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.address = address

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not self.address:
            return super().handle_request(request)
        inner = httpx.Request(request.method, request.url.copy_with(host=self.address),
                              headers=request.headers, stream=request.stream,
                              extensions={**request.extensions,
                                          "sni_hostname": request.url.host})
        return super().handle_request(inner)


class Site:
    def __init__(self) -> None:
        self.url = os.environ["SD_E2E_URL"].rstrip("/")
        ca = os.environ.get("SD_E2E_CA")
        self.verify: Any = ca if ca else False
        self.address = os.environ.get("SD_E2E_CONNECT", "")

    def client(self) -> httpx.Client:
        return httpx.Client(base_url=self.url, timeout=httpx.Timeout(60, connect=15),
                            transport=PinnedTransport(self.address, verify=self.verify))


class Api:
    """One signed-in browser: its own cookies and CSRF header."""

    def __init__(self, site: Site) -> None:
        self.http = site.client()
        self.account: dict[str, Any] = {}

    def sign_in(self, email: str, password: str) -> Api:
        r = self.http.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        self._signed_in(r.json())
        return self

    def set_password(self, token: str, password: str) -> Api:
        r = self.http.post("/api/auth/password/set", json={"token": token, "password": password})
        assert r.status_code == 200, r.text
        self._signed_in(r.json())
        return self

    def _signed_in(self, body: dict[str, Any]) -> None:
        self.account = body["account"]
        self.http.headers["x-csrf-token"] = body["csrf_token"]

    def call(self, method: str, path: str, expect: int | None = 200, **kw: Any) -> Any:
        r = self.http.request(method, path, **kw)
        if expect is not None:
            assert r.status_code == expect, f"{method} {path}: {r.status_code} {r.text[:500]}"
        return r.json() if r.content and "json" in r.headers.get("content-type", "") else r

    def my_files(self) -> str:
        return str(self.call("GET", "/api/files/roots")["roots"][0]["path"])

    def write_text(self, path: str, text: str) -> None:
        self.call("PUT", "/api/files/text", params={"path": path}, content=text.encode())

    def submit(self, intent: str, **spec: Any) -> str:
        base = self.call("GET", "/api/jobs/defaults", params={"intent": intent})["spec"]
        small = {"gpu_shards": 0, "cpus": 1, "mem_gb": 1, "time_limit": "00:05:00",
                 "env_kind": "none", "mail": False}
        return str(self.call("POST", "/api/jobs", expect=201,
                             json={**base, **small, **spec, "intent": intent})["job_id"])

    def job(self, job_id: str) -> dict[str, Any]:
        return dict(self.call("GET", f"/api/jobs/{job_id}"))

    def wait_job(self, job_id: str, states: set[str], timeout: float = JOB_WAIT
                 ) -> dict[str, Any]:
        return wait_for(lambda: (d if (d := self.job(job_id))["state"] in states else None),
                        timeout, f"job {job_id} to reach {sorted(states)}", every=10)


def psql(sql: str) -> str:
    r = subprocess.run([*shlex.split(PSQL), sql], stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def last_link(to_addr: str) -> str:
    """The newest one-time link mailed to to_addr, read from the outbox."""
    quoted = to_addr.replace("'", "''")
    out = wait_for(lambda: psql(f"SELECT text FROM outbox WHERE to_addr = '{quoted}' "
                                "ORDER BY id DESC LIMIT 1"), 60, f"mail to {to_addr}", 2)
    m = TOKEN_RE.search(out)
    assert m, f"no link in the mail to {to_addr}"
    return m.group(1)


def new_password() -> str:
    return secrets.token_urlsafe(18) + "-Aa1"


class Accounts:
    """Throwaway accounts made through the admin API, deleted at the end."""

    def __init__(self, site: Site, admin: Api) -> None:
        self.site, self.admin = site, admin
        self.made: dict[str, dict[str, Any]] = {}

    def email(self, name: str) -> str:
        return EMAIL.format(name=name)

    def create(self, suffix: str, **extra: Any) -> dict[str, Any]:
        name = f"{PREFIX}{suffix}"
        row = self.admin.call("POST", "/api/admin/accounts", json={
            "email": self.email(name), "full_name": f"Acceptance test {name}",
            "username": name, **extra})
        self.made[name] = row
        return dict(row)

    def sign_in_new(self, row: dict[str, Any]) -> Api:
        return Api(self.site).set_password(last_link(row["email"]), new_password())

    def delete(self, name: str, purge: bool = True) -> None:
        row = self.made.pop(name)
        self.admin.call("DELETE", f"/api/admin/accounts/{row['id']}",
                        params={"purge": str(purge).lower()},
                        json={"confirm": name} if purge else None)
