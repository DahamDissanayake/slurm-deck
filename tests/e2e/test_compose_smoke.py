"""Compose smoke test, on a host with Docker and the site's env files.

Opt-in: SD_E2E=1 pytest tests/e2e. Run from deploy/ after `docker compose up -d`.
"""

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("SD_E2E") != "1",
                                reason="set SD_E2E=1 to run against a live Compose stack")

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def _compose(*args: str) -> str:
    return subprocess.run(["docker", "compose", *args], cwd=DEPLOY, check=True,
                          capture_output=True, text=True).stdout


def test_apply_open_answers_through_caddy():
    import httpx

    r = httpx.get("https://localhost/api/public/apply-open", verify=False, timeout=10)
    assert r.status_code == 200


def test_http_redirects_to_https():
    import httpx

    r = httpx.get("http://localhost/", timeout=10)
    assert r.status_code in (301, 308) and r.headers["location"].startswith("https://")


@pytest.mark.parametrize("service", ["web", "worker"])
def test_app_containers_do_not_run_as_root(service):
    assert _compose("exec", "-T", service, "id", "-u").strip() != "0"
