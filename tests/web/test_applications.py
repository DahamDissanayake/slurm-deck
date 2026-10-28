"""The public Apply form and the admin decision."""

import threading

import pytest
from accounts_helpers import _client, _rows

pytestmark = pytest.mark.pg

FORM = {"email": " Amasha@IIT.ac.lk ", "full_name": "Amasha <b>P</b>", "role_title": "Student",
        "contact_number": "0771234567", "reason": "Train models"}
REFUSED = "Applications from this email aren't open — contact the cluster admin."
RECEIVED = "Application received — you'll get an email once an admin reviews it."


@pytest.fixture
def site(admin):
    from fastapi.testclient import TestClient

    app, agent, outbox, c = admin
    c.post("/api/admin/allowlist", json={"value": "iit.ac.lk"})
    public = TestClient(app, base_url="https://testserver", client=("10.0.0.7", 4000))
    return app, agent, outbox, c, public


def _apps(app):
    from sqlalchemy import select

    from sdweb.models import Application

    with app.state.sessionmaker() as s:
        return s.scalars(select(Application).order_by(Application.id)).all()


def _pending(site) -> int:
    _, _, _, _, public = site
    assert public.post("/api/public/applications", json=FORM).status_code == 201
    return _apps(site[0])[-1].id


def test_apply_stores_and_mails_admins(site):
    app, _, outbox, _, public = site
    r = public.post("/api/public/applications", json=FORM)
    assert (r.status_code, r.json()) == (201, {"message": RECEIVED})
    [row] = _apps(app)
    assert (row.email, row.status, str(row.ip)) == ("amasha@iit.ac.lk", "pending", "10.0.0.7")
    assert sorted(to for to, kind, _ in outbox if kind == "application_received_admin") == [
        "dinuka@x.org", "kasun@x.org"]
    r = public.post("/api/public/applications", json=FORM)
    assert r.status_code == 409 and r.json()["message"] == \
        "You already have an application waiting for review."


def test_empty_allowlist_closes_form(env):
    from fastapi.testclient import TestClient

    public = TestClient(env[0], base_url="https://testserver")
    assert public.get("/api/public/apply-open").json() == {"open": False}
    r = public.post("/api/public/applications", json=FORM)
    assert (r.status_code, r.json()["message"]) == (403, REFUSED)


def test_refused_email_is_not_stored(site):
    app, _, outbox, _, public = site
    for email in ("a@gmail.com", "a@cs.iit.ac.lk"):
        r = public.post("/api/public/applications", json={**FORM, "email": email})
        assert (r.status_code, r.json()["message"]) == (403, REFUSED)
    assert _apps(app) == [] and outbox == []


def test_honeypot_pretends_success_stores_nothing(site):
    app, _, outbox, _, public = site
    r = public.post("/api/public/applications", json={**FORM, "website": "http://spam"})
    assert (r.status_code, r.json()) == (201, {"message": RECEIVED})
    assert _apps(app) == [] and outbox == []


def test_per_ip_limit(site):
    _, _, _, _, public = site
    for i in range(5):
        assert public.post("/api/public/applications",
                           json={**FORM, "email": f"u{i}@iit.ac.lk"}).status_code == 201
    assert public.post("/api/public/applications",
                       json={**FORM, "email": "u9@iit.ac.lk"}).status_code == 429


def test_approve_creates_the_account_and_sends_the_link(site):
    app, agent, outbox, c, _ = site
    app_id = _pending(site)
    r = c.post(f"/api/admin/applications/{app_id}/approve", json={"username": "amasha"})
    assert r.status_code == 200, r.text
    [row] = _apps(app)
    assert (row.status, row.account_id) == ("approved", _rows(app, "amasha")[0].id)
    kinds = [kind for to, kind, _ in outbox if to == "amasha@iit.ac.lk"]
    assert kinds == ["application_approved"]                  # no separate set_password mail
    assert c.get("/api/admin/applications").json()["applications"] == []


def test_concurrent_approve_creates_one_account(site):
    app, _, _, c, _ = site
    app_id = _pending(site)
    other = _client(app, "kasun")
    codes: list[int] = []

    def go(client):
        codes.append(client.post(f"/api/admin/applications/{app_id}/approve",
                                 json={"username": "amasha"}).status_code)

    threads = [threading.Thread(target=go, args=(x,)) for x in (c, other)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [200, 409]
    assert len(_rows(app, "amasha")) == 1


def test_reject_sends_note(site):
    app, _, outbox, c, _ = site
    app_id = _pending(site)
    r = c.post(f"/api/admin/applications/{app_id}/reject", json={"note": "Use your lab email"})
    assert r.status_code == 200
    assert outbox[-1] == ("amasha@iit.ac.lk", "application_rejected",
                          {"note": "Use your lab email"})
    assert _apps(app)[0].status == "rejected"
    assert c.post(f"/api/admin/applications/{app_id}/reject", json={}).status_code == 409
