"""/api/models against a fake deck-agent: the library, downloads and the token's path."""

import pytest
from accounts_helpers import _account, _client
from sqlalchemy import select

from sdweb.models import AuditEvent, Job

pytestmark = pytest.mark.pg

SHARED = "/shared/models"
MINE = "/shared/users/amasha/models"
TOKEN = "hf_secrettoken123"


class ModelsAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.live: list[str] = []
        self.logs: dict[str, bytes] = {}

    def call(self, verb, payload=None, *, session=None):
        self.calls.append((verb, payload))
        if verb == "fs.list":
            return {"entries": {SHARED: [{"name": "llama", "type": "dir", "size": 4096},
                                         {"name": "notes.txt", "type": "file", "size": 12}]
                                }.get(payload["path"], [])}
        return {"fs.du": {"bytes": 5_000_000},
                "job.submit": {"job_id": "700", "folder": "/shared/jobs/amasha/hf"},
                "job.list": {"jobs": [{"job_id": j} for j in self.live]}}.get(verb, {})

    def stream_with_headers(self, verb, payload=None, *, session=None):
        return {}, iter([self.logs.get(payload["job_id"], b"")])


@pytest.fixture
def models(env):
    app, _, _ = env
    app.state.agent = ModelsAgent()
    _account(app, "amasha")
    return app, app.state.agent, _client(app, "amasha")


def _submit(c, **body):
    return c.post("/api/models/download", json={"repo_id": "meta-llama/Llama-3.1-8B", **body})


def test_library_lists_shared_and_my_models_with_sizes(models):
    _, _, c = models
    r = c.get("/api/models").json()
    assert r["shared"] == [{"name": "llama", "type": "dir", "bytes": 5_000_000},
                           {"name": "notes.txt", "type": "file", "bytes": 12}]
    assert r["mine"] == []


def test_the_token_goes_to_the_job_folder_only(models):
    app, agent, c = models
    assert _submit(c, token=f"  {TOKEN} ").status_code == 201
    _, payload = next(x for x in agent.calls if x[0] == "job.submit")
    assert payload["secret_file"] == {"name": ".hf_token", "content": TOKEN}
    assert TOKEN not in payload["script"]
    assert f"{MINE}/meta-llama--Llama-3.1-8B" in payload["script"]
    with app.state.sessionmaker() as s:
        assert s.get(Job, "700").kind == "model_download" and TOKEN not in s.get(Job, "700").script
        audit = s.scalars(select(AuditEvent).where(AuditEvent.action == "model.download")).one()
        assert audit.detail == {"job_id": "700", "with_token": True}


def test_a_public_model_needs_no_token(models):
    _, agent, c = models
    assert _submit(c, revision="main").status_code == 201
    _, payload = next(x for x in agent.calls if x[0] == "job.submit")
    assert "secret_file" not in payload


@pytest.mark.parametrize("body", [{"repo_id": "no-slash"}, {"repo_id": "a/b;id"},
                                  {"repo_id": "../x/y"}, {"revision": "x y"},
                                  {"token": "has space"}])
def test_bad_input_is_422(models, body):
    _, agent, c = models
    r = c.post("/api/models/download", json={"repo_id": "org/name", **body})
    assert r.status_code == 422
    assert not any(x[0] == "job.submit" for x in agent.calls)


def test_downloads_report_done_failed_and_running(models):
    app, agent, c = models
    from sdweb.models import Account

    with app.state.sessionmaker() as s, s.begin():
        owner = s.query(Account).filter_by(username="amasha").one()
        for jid, repo in (("1", "org/done"), ("2", "org/gated"), ("3", "org/busy"),
                          ("4", "org/lost")):
            s.add(Job(job_id=jid, account_id=owner.id, kind="model_download", name=repo,
                      folder="/f", spec={"model_path": repo}, script=""))
    agent.logs = {"1": b"SD_HF_DONE 123456\n", "2": b"SD_HF_FAIL auth\n"}
    agent.live = ["3"]
    got = {d["repo_id"]: d for d in c.get("/api/models/downloads").json()["downloads"]}
    assert (got["org/done"]["state"], got["org/done"]["bytes"]) == ("done", 123456)
    assert got["org/gated"]["message"] == "HuggingFace refused the token for this repository."
    assert got["org/busy"]["state"] == "running" and got["org/lost"]["state"] == "failed"
