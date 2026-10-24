"""Allow-list matching and its admin API."""

import pytest

from sdweb.accounts.allowlist import matches
from sdweb.models import AllowEntry


def dom(v):
    return AllowEntry(kind="domain", value=v)


def addr(v):
    return AllowEntry(kind="address", value=v)


@pytest.mark.parametrize("email,ok", [
    ("a@iit.ac.lk", True), ("A@IIT.AC.LK", True), (" a@iit.ac.lk ", True),
    ("a@cs.iit.ac.lk", False), ("a@iit.ac.lk.evil.com", False),
    ("partner@company.com", True), ("Partner@Company.com", True), ("other@company.com", False),
])
def test_matching(email, ok):
    assert matches([dom("iit.ac.lk"), addr("partner@company.com")], email) is ok
    assert matches([], email) is False


@pytest.mark.pg
def test_admin_manages_the_list_and_it_opens_the_form(admin):
    from fastapi.testclient import TestClient

    app, _, _, c = admin
    public = TestClient(app, base_url="https://testserver")
    assert public.get("/api/public/apply-open").json() == {"open": False}
    r = c.post("/api/admin/allowlist", json={"value": "IIT.ac.lk"})
    assert r.status_code == 201 and r.json()["kind"] == "domain"
    assert c.post("/api/admin/allowlist", json={"value": "Partner@Company.com"}).json()["kind"] \
        == "address"
    assert c.post("/api/admin/allowlist", json={"value": "iit.ac.lk"}).status_code == 409
    assert c.post("/api/admin/allowlist", json={"value": "not a domain"}).status_code == 422
    assert public.get("/api/public/apply-open").json() == {"open": True}
    entries = c.get("/api/admin/allowlist").json()["entries"]
    assert {e["value"] for e in entries} == {"iit.ac.lk", "partner@company.com"}
    for e in entries:
        assert c.delete(f"/api/admin/allowlist/{e['id']}").status_code == 200
    assert public.get("/api/public/apply-open").json() == {"open": False}
    assert public.post("/api/admin/allowlist", json={"value": "x.org"}).status_code == 401
