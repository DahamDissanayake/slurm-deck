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
