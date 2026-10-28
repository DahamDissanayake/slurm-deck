"""Password, token and email helpers, and the web audit writer."""

import pytest

from sdweb.security import (
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    normalize_email,
    password_problems,
    valid_email,
    verify_password,
)

SHORT, COMMON, PERSONAL = ("Use at least 12 characters.", "That password is too common.",
                           "Don't use your email or username.")


def _problems(pw, email="amasha@iit.ac.lk", username="amasha"):
    return password_problems(pw, email=email, username=username)


def test_password_problems():
    assert _problems("short")[0] == SHORT              # "short" is also on the list
    assert _problems("Xq7-pz") == [SHORT]
    assert _problems("unbelievable") == [COMMON]
    assert _problems("UnBelievable") == [COMMON]          # case doesn't help
    assert _problems("my-AMASHA-secret") == [PERSONAL]
    assert _problems("amasha@iit.ac.lk!") == [PERSONAL]
    assert _problems("Amasha") == [SHORT, PERSONAL]
    assert _problems("password") == [SHORT, COMMON]
    assert _problems("correct horse battery staple") == []


def test_hashing_round_trip():
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple")
    assert not verify_password(h, "correct horse battery stapl")
    assert not verify_password("not-a-hash", "x")
    assert needs_rehash(h) is False


def test_normalize_email():
    assert normalize_email("  Amasha@IIT.ac.lk ") == "amasha@iit.ac.lk"


@pytest.mark.parametrize("addr, ok", [
    ("amasha@iit.ac.lk", True), ("a@b.co", True),
    ("amasha", False), ("@iit.ac.lk", False), ("a@b@c.com", False), ("a@localhost", False),
    ("a b@c.com", False), ("a@b.com\n", False), ("a@" + "b" * 250 + ".com", False),
    ("a@.com", False), ("a@b.", False),
])
def test_valid_email(addr, ok):
    assert valid_email(addr) is ok


def test_tokens_are_long_and_unique():
    tokens = {new_token() for _ in range(100)}
    assert len(tokens) == 100 and all(len(t) >= 43 for t in tokens)
    assert hash_token("abc") == ("ba7816bf8f01cfea414140de5dae2223"
                                 "b00361a396177a9cb410ff61f20015ad")


@pytest.mark.pg
def test_record_writes_audit_events(pg_db):
    from sqlalchemy import select

    from sdweb import db
    from sdweb.audit import record
    from sdweb.config import load_settings
    from sdweb.models import AuditEvent

    db.configure(load_settings({"SD_DATABASE_URL": pg_db.dsn}))
    with db.session_scope() as s:
        record(s, actor_id=None, action="account.create", target="amasha",
               detail={"role": "user"})
        record(s, actor_id=None, action="mail.send", result="failed", source="worker")
    with db.session_scope() as s:
        rows = s.scalars(select(AuditEvent).order_by(AuditEvent.id)).all()
        got = [(r.action, r.target, r.detail, r.result, r.source) for r in rows]
    assert got == [("account.create", "amasha", {"role": "user"}, "ok", "web"),
                   ("mail.send", "", {}, "failed", "worker")]


def test_common_list_loads_in_full():
    from sdweb.security import _common

    words = _common()
    assert len(words) >= 10000 and {"password", "123456", "unbelievable"} <= words
