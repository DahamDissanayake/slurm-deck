"""The spec's §13 acceptance scenarios, at API level, against a real install.

Opt-in: SD_E2E=1 (see conftest.py for the other settings). Scenarios 8 and 13
and the browser checks are manual: docs/operations/acceptance-checklist.md.
Every job asks for no GPU pod, 1 CPU, 1 GB and a few minutes.
"""

from __future__ import annotations

import base64
import os
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from e2e_support import (
    JOB_WAIT,
    PREFIX,
    Accounts,
    Api,
    Site,
    last_link,
    new_password,
    wait_for,
)

ENDED = {"COMPLETED", "FAILED", "OUT_OF_MEMORY", "TIMEOUT", "CANCELLED", "NODE_FAIL"}
MIB = 1024 ** 2


def _cancel(api: Api, job_id: str) -> None:
    api.call("POST", f"/api/jobs/{job_id}/cancel", expect=None)


def _session_ready(api: Api, job_id: str) -> dict[str, Any] | None:
    d = api.job(job_id)
    assert d["state"] not in ENDED, f"session job {job_id} ended: {d['state']}"
    return d if d["session"] and d["session"]["ready"] else None


def test_scenario_1_notebook_opens(alice: Api) -> None:
    job_id = alice.submit("notebook", time_limit="00:15:00", mem_gb=2)
    try:
        d = wait_for(lambda: _session_ready(alice, job_id), JOB_WAIT, "the notebook", 10)
        assert d["session"]["open_url"] == f"/notebook/{job_id}/lab"
        base = f"/notebook/{job_id}"
        # The app origin hands over to the session origin; JupyterLab answers there.
        r = alice.http.get(f"{base}/api/status", follow_redirects=True)
        assert r.status_code == 200 and "started" in r.json(), r.text[:300]
        # A scratch file can be made and deleted (no .Trash 500).
        session = str(r.url).split(base)[0]
        put = alice.http.put(f"{session}{base}/api/contents/scratch.txt",
                             json={"type": "file", "format": "text", "content": "x"})
        assert put.status_code in (200, 201), put.text[:300]
        gone = alice.http.delete(f"{session}{base}/api/contents/scratch.txt")
        assert gone.status_code == 204, gone.text[:300]
    finally:
        _cancel(alice, job_id)


class _Interrupted(Exception):
    pass


def _bytes(n: int, stop_after: int | None = None) -> Iterator[bytes]:
    block = os.urandom(MIB)
    sent = 0
    while sent < n:
        if stop_after is not None and sent >= stop_after:
            raise _Interrupted   # the laptop lid closes mid-chunk
        piece = block[:min(MIB, n - sent)]
        sent += len(piece)
        yield piece


def test_scenario_2_upload_resumes(alice: Api) -> None:
    size = int(float(os.environ.get("SD_E2E_UPLOAD_GB", "20")) * 1024 ** 3)
    chunk = 64 * MIB   # the upload panel's chunk size; Caddy allows 128 MB
    dest = alice.my_files()
    meta = f"filename {_b64('standin.bin')},dest_dir {_b64(dest)}"
    r = alice.call("POST", "/api/uploads", expect=201,
                   headers={"Tus-Resumable": "1.0.0", "Upload-Length": str(size),
                            "Upload-Metadata": meta})
    url = r.headers["location"]
    tus = {"Tus-Resumable": "1.0.0", "Content-Type": "application/offset+octet-stream"}
    try:
        try:   # the client may raise, or the server may answer the short body
            cut = alice.http.patch(url, headers={**tus, "Upload-Offset": "0",
                                                 "Content-Length": str(min(chunk, size))},
                                   content=_bytes(min(chunk, size), stop_after=chunk // 2))
            assert cut.status_code != 204, "the interrupted chunk was accepted whole"
        except (_Interrupted, httpx.HTTPError):
            pass
        offset = int(alice.call("HEAD", url).headers["upload-offset"])
        assert 0 <= offset < size
        while offset < size:
            n = min(chunk, size - offset)
            r = alice.call("PATCH", url, expect=204, content=_bytes(n),
                           headers={**tus, "Upload-Offset": str(offset), "Content-Length": str(n)})
            offset = int(r.headers["upload-offset"])
        st = alice.call("GET", "/api/files/stat", params={"path": f"{dest}/standin.bin"})
        assert st["size"] == size
    finally:
        alice.call("POST", "/api/files/delete", expect=None,
                   json={"path": f"{dest}/standin.bin"})


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _script(api: Api, name: str, body: str) -> str:
    path = f"{api.my_files()}/{name}"
    api.write_text(path, f"#!/bin/bash\n{body}\n")
    return path


def test_scenario_3_extend_then_refused_at_cap(alice: Api) -> None:
    job_id = alice.submit("batch", script=_script(alice, "wait.sh", "sleep 240"))
    try:
        first = alice.call("POST", f"/api/jobs/{job_id}/extend", json={"hours": 1})
        assert first["new_limit_s"] == 5 * 60 + 3600
        assert alice.job(job_id)["time_limit_s"] == first["new_limit_s"]
        for _ in range(12):
            r = alice.http.post(f"/api/jobs/{job_id}/extend", json={"hours": 4})
            if r.status_code != 200:
                break
        assert r.status_code == 422 and r.json()["error"] == "over_cap", r.text
        assert "the limit is" in r.json()["message"]
    finally:
        _cancel(alice, job_id)


def test_scenario_4_oom_is_explained(alice: Api) -> None:
    hog = "head -c 3000m /dev/zero | tail > /dev/null"   # holds 3 GB in a 1 GB job
    job_id = alice.submit("batch", script=_script(alice, "hog.sh", hog))
    d = alice.wait_job(job_id, ENDED)
    assert d["state"] == "OUT_OF_MEMORY", d["state"]
    assert d["explanation"].startswith("Out of memory: the job used more than its 1 GB RAM")


def test_scenario_5_array_after_dependency(alice: Api) -> None:
    prep = alice.submit("batch", script=_script(alice, "prep.sh", "sleep 5"))
    sweep = alice.submit("batch", script=_script(alice, "sweep.sh", "sleep 5"),
                         array="0-3%2", dependency=f"afterok:{prep}")
    tasks = {f"{sweep}_{i}" for i in range(4)}

    def all_done() -> set[str] | None:
        rows = alice.call("GET", "/api/jobs/history", params={"days": 1})["jobs"]
        done = {j["job_id"] for j in rows if j["job_id"] in tasks and j["state"] == "COMPLETED"}
        return done if done == tasks else None
    assert wait_for(all_done, JOB_WAIT, "every array task to complete", 15) == tasks
    assert alice.job(prep)["state"] == "COMPLETED"


@pytest.fixture(scope="session")
def built_env(alice: Api) -> dict[str, Any]:
    """Scenario 7's env: built from a requirements.txt that names tensorboard."""
    req = f"{alice.my_files()}/requirements.txt"
    alice.write_text(req, "tensorboard\n")
    job_id = alice.call("POST", "/api/envs/build", expect=201,
                        json={"kind": "venv", "name": "acceptenv",
                              "requirements_path": req})["job_id"]

    def finished() -> dict[str, Any] | None:
        out = alice.call("GET", "/api/envs")
        build = next(b for b in out["builds"] if b["job_id"] == job_id)
        if build["state"] == "building":
            return None
        return {"build": build, "env": next((e for e in out.get("mine", [])
                                             if e["path"] == build["path"]), None)}
    return wait_for(finished, JOB_WAIT, "the env build", 15)


def test_scenario_7_env_build_verified(built_env: dict[str, Any]) -> None:
    assert built_env["build"]["state"] == "ok", built_env["build"]
    assert built_env["build"]["missing"] == []
    assert built_env["env"] is not None and built_env["env"]["ready"] is True


def test_scenario_6_tensorboard_only_for_its_owner(alice: Api, bob: Api,
                                                   built_env: dict[str, Any]) -> None:
    runs = f"{alice.my_files()}/runs"
    alice.call("POST", "/api/files/mkdir", expect=None, json={"path": runs})
    job_id = alice.submit("tensorboard", data_path=runs, time_limit="00:15:00", mem_gb=2,
                          env_kind="venv", venv_path=built_env["build"]["path"])
    try:
        wait_for(lambda: _session_ready(alice, job_id), JOB_WAIT, "TensorBoard", 10)
        mine = alice.http.get(f"/tensorboard/{job_id}/", follow_redirects=True)
        assert mine.status_code == 200, mine.text[:300]
        theirs = bob.http.get(f"/tensorboard/{job_id}/", follow_redirects=True)
        assert theirs.status_code == 403
        assert "not your session" in theirs.text.lower()
    finally:
        _cancel(alice, job_id)


def test_scenario_9_notify_mails_once(admin: Api, bob: Api) -> None:
    wait_for(lambda: (s := bob.call("GET", "/api/cluster/status"))["pods_total"]
             - s["pods_used"] >= 1, JOB_WAIT, "a free pod", 30)
    bob.call("PUT", "/api/notify", json={"wanted_pods": 1})
    to = bob.account["email"]

    def mails() -> list[dict[str, Any]]:
        rows = admin.call("GET", "/api/admin/mail-log", params={"page_size": 200})["mail"]
        return [m for m in rows if m["to"] == to and m["kind"] == "pods_free"]
    wait_for(mails, 300, "the pods-free mail", 10)
    assert bob.call("GET", "/api/notify")["wanted_pods"] is None   # consumed
    time.sleep(90)   # the worker passes again; no second mail
    assert len(mails()) == 1


def test_scenario_10_allow_list(site: Site, admin: Api, accounts: Accounts) -> None:
    name = f"{PREFIX}partner"
    partner = accounts.email(name)
    entry = admin.call("POST", "/api/admin/allowlist", expect=201, json={"value": partner})
    try:
        public = site.client()
        form = {"full_name": "Acceptance partner", "role_title": "Engineer",
                "contact_number": "0000000000", "organisation": "Acceptance test"}
        r = public.post("/api/public/applications", json={**form, "email": partner})
        assert r.status_code == 201, r.text
        refused = public.post("/api/public/applications",
                              json={**form, "email": "sdtest.friend@gmail.com"})
        assert refused.status_code == 403 and refused.json()["error"] == "not_allowed"
        app = next(a for a in admin.call("GET", "/api/admin/applications")["applications"]
                   if a["email"] == partner)
        out = admin.call("POST", f"/api/admin/applications/{app['id']}/approve",
                         json={"username": name, "role": "user"})
        accounts.made[name] = {"id": out["account_id"], "email": partner}
        row = next(a for a in admin.call("GET", "/api/admin/accounts",
                                         params={"q": name})["accounts"]
                   if a["username"] == name)
        assert row["role"] == "user" and row["status"] == "active"
    finally:
        admin.call("DELETE", f"/api/admin/allowlist/{entry['id']}", expect=None)


@pytest.mark.skipif(not os.environ.get("SD_E2E_RETURNING_USER"),
                    reason="stage an old folder and set SD_E2E_RETURNING_USER")
def test_scenario_11_reconnect_keeps_folder(site: Site, admin: Api,
                                            accounts: Accounts) -> None:
    name = os.environ["SD_E2E_RETURNING_USER"]
    found = admin.call("POST", "/api/admin/accounts/preview",
                       json={"email": accounts.email(name), "username": name})
    folder = found["existing_folder"]
    assert folder and folder["exists"] and not folder["uid_in_use"], found
    row = admin.call("POST", "/api/admin/accounts", json={
        "email": accounts.email(name), "full_name": "Returning user", "username": name,
        "reconnect_folder": True})
    accounts.made[name] = row
    assert row["uid"] == folder["owner_uid"]
    user = Api(site).set_password(last_link(row["email"]), new_password())
    notes = user.call("GET", "/api/files/text",
                      params={"path": f"{user.my_files()}/PlurVa/notes.txt"})
    assert notes["text"].strip() == "returning user's project"


@pytest.mark.skipif(os.environ.get("SD_E2E_DISRUPTIVE") != "1",
                    reason="drains the node: set SD_E2E_DISRUPTIVE=1 on a quiet cluster")
def test_scenario_12_drain_and_resume_are_audited(admin: Api) -> None:
    reason = "acceptance test: drain and resume"
    out = admin.call("POST", "/api/admin/node/drain",
                     json={"reason": reason, "cancel_running": False})
    try:
        assert out["cancelled"] == []
    finally:
        admin.call("POST", "/api/admin/node/resume", json={})
    log = str(admin.call("GET", "/api/admin/agent-audit", params={"limit": 50}))
    assert "admin.drain" in log and "admin.resume" in log and reason in log


def test_scenario_14_delete_archives_and_uid_is_never_reused(admin: Api,
                                                             accounts: Accounts) -> None:
    gone = accounts.create("del")
    accounts.delete(gone["username"], purge=False)
    found = admin.call("POST", "/api/admin/accounts/preview",
                       json={"email": accounts.email("x"), "username": gone["username"]})
    assert found["existing_folder"] is None   # renamed to <name>.offboarded
    names = [a["username"] for a in admin.call("GET", "/api/admin/accounts")["accounts"]]
    assert gone["username"] not in names
    nxt = accounts.create("next")
    assert nxt["uid"] != gone["uid"] and nxt["uid"] > gone["uid"]
