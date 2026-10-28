"""Upload grants: HMAC over username|upload_id|expires."""

import pytest

from deckagent.grants import issue, verify
from deckagent.protocol import AgentError

KEY = b"k" * 32
NOW = 1_800_000_000


def _refused(grant: str, upload_id: str = "upl-amasha-1", now: int = NOW, key: bytes = KEY):
    with pytest.raises(AgentError) as e:
        verify(key, grant, upload_id=upload_id, now=now)
    assert (e.value.code, e.value.status) == ("bad_grant", 403)


def test_grant_bound_to_user_and_upload():
    g = issue(KEY, username="amasha", upload_id="upl-amasha-1", expires=NOW + 60)
    assert verify(KEY, g, upload_id="upl-amasha-1", now=NOW) == "amasha"
    _refused(g, upload_id="upl-bob-0001")           # B's upload with A's grant


def test_expired_grant_refused():
    g = issue(KEY, username="amasha", upload_id="upl-amasha-1", expires=NOW)
    _refused(g, now=NOW + 1)


@pytest.mark.parametrize("tamper", [
    lambda g: g[:-2] + ("AA" if not g.endswith("AA") else "BB"),
    lambda g: g.replace("amasha", "bobbie"),
    lambda g: "not-a-grant",
    lambda g: "",
])
def test_tampered_grant_refused(tamper):
    g = issue(KEY, username="amasha", upload_id="upl-amasha-1", expires=NOW + 60)
    _refused(tamper(g))
    _refused(g, key=b"x" * 32)


class _Store:
    """account() lookups for the status check, counted."""

    def __init__(self, status: dict[str, str]):
        self.status, self.lookups = status, 0

    def account(self, username):
        from types import SimpleNamespace

        self.lookups += 1
        s = self.status.get(username)
        return SimpleNamespace(status=s) if s else None


def _inactive(check, store, username):
    with pytest.raises(AgentError) as e:
        check(store, username)
    assert (e.value.code, e.value.status) == ("account_inactive", 403)


def test_account_check_refuses_disabled_missing_and_no_store():
    from deckagent.grants import ActiveAccounts

    check = ActiveAccounts().check
    store = _Store({"amasha": "active", "bob": "disabled"})
    check(store, "amasha")
    _inactive(check, store, "bob")
    _inactive(check, store, "nobody")
    _inactive(ActiveAccounts().check, None, "amasha")   # fresh cache: no store


def test_account_check_is_cached_for_a_minute_per_username():
    from deckagent.grants import ActiveAccounts

    now = [1000.0]
    check = ActiveAccounts(ttl=60, clock=lambda: now[0]).check
    store = _Store({"amasha": "active"})
    check(store, "amasha")
    check(store, "amasha")
    assert store.lookups == 1                     # one lookup, then the cache
    store.status["amasha"] = "disabled"
    now[0] += 59
    check(store, "amasha")                        # still cached
    now[0] += 2
    _inactive(check, store, "amasha")             # re-read after 60 s
    assert store.lookups == 2


def test_grant_lifetime_is_short_and_web_matches():
    from deckagent.grants import GRANT_SECONDS
    from sdweb.files.tus import GRANT_LIFE, REGRANT_BEFORE

    assert GRANT_SECONDS <= 3600
    assert GRANT_LIFE.total_seconds() == GRANT_SECONDS
    assert REGRANT_BEFORE.total_seconds() < GRANT_SECONDS
