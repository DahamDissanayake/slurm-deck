"""Fixtures for the acceptance scenarios (spec §13) against a real install.

Opt-in: SD_E2E=1. The run signs in as a throwaway admin and makes throwaway
web accounts, all named with SD_E2E_PREFIX (default sdtest), and deletes them
again at the end through the admin API. See docs/operations/acceptance-checklist.md.

SD_E2E_URL              the app, e.g. https://slurmdeck.local
SD_E2E_CONNECT          optional address to connect to instead of DNS (both the app
                        and the session hostname go there; SNI and Host stay the names)
SD_E2E_CA               optional CA file for the site's certificate (else no verify)
SD_E2E_ADMIN_EMAIL      a throwaway admin, made with `sdweb.cli create-admin --force`
SD_E2E_ADMIN_PASSWORD   and listed in deck-agent's admins file for the run
SD_E2E_PSQL             command that runs one SQL statement on the web database and
                        prints rows (used only to read set-password links from the outbox)
SD_E2E_EMAIL            address template for the throwaway accounts, {name} is filled in
SD_E2E_RETURNING_USER   a staged old folder for scenario 11 (else scenario 11 skips)
SD_E2E_DISRUPTIVE=1     allow scenario 12 (drains and resumes the node)
SD_E2E_UPLOAD_GB        size of the scenario 2 stand-in upload (default 20)
SD_E2E_JOB_WAIT         seconds to wait for a job to start or end (default 1800)
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from e2e_support import Accounts, Api, Site

if os.environ.get("SD_E2E") != "1":
    collect_ignore = ["test_scenarios.py"]


@pytest.fixture(scope="session")
def site() -> Site:
    return Site()


@pytest.fixture(scope="session")
def admin(site: Site) -> Api:
    return Api(site).sign_in(os.environ["SD_E2E_ADMIN_EMAIL"],
                             os.environ["SD_E2E_ADMIN_PASSWORD"])


@pytest.fixture(scope="session")
def accounts(site: Site, admin: Api) -> Iterator[Accounts]:
    made = Accounts(site, admin)
    yield made
    for name in list(made.made):   # jobs are cancelled by the delete itself
        made.delete(name)


@pytest.fixture(scope="session")
def alice(accounts: Accounts) -> Api:
    return accounts.sign_in_new(accounts.create("1"))


@pytest.fixture(scope="session")
def bob(accounts: Accounts) -> Api:
    return accounts.sign_in_new(accounts.create("2"))

