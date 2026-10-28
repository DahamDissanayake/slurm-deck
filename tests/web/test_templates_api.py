"""Saved launch templates are private to each account."""

import pytest
from accounts_helpers import _account, _client

pytestmark = pytest.mark.pg


def test_template_names_per_account(env):
    app = env[0]
    _account(app, "amasha")
    _account(app, "hassan")
    a, h = _client(app, "amasha"), _client(app, "hassan")
    body = {"name": "train", "spec": {"intent": "batch", "cpus": 4}}
    assert a.post("/api/templates", json=body).status_code == 201
    assert h.post("/api/templates", json=body).status_code == 201       # same name, other account
    assert a.post("/api/templates", json=body).status_code == 409
    mine = a.get("/api/templates").json()
    assert mine["presets"] == [] and [t["spec"]["cpus"] for t in mine["templates"]] == [4]
    theirs = h.get("/api/templates").json()["templates"][0]["id"]
    assert a.delete(f"/api/templates/{theirs}").status_code == 404
    assert h.delete(f"/api/templates/{theirs}").status_code == 200
    assert a.post("/api/templates", json={"name": "x", "spec": {"bogus": 1}}).status_code == 422
