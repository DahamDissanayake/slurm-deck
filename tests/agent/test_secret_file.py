"""job.submit's secret_file: a HuggingFace token written 0600 beside the script."""

import stat

import pytest
from test_verbs_jobs import _err, jobs  # noqa: F401  (jobs is a fixture)

from sdcore.hfdownload import render_hf_download

NAME = "hf-org--model_20261025_120000"


def _payload(agent, **extra):
    root = str(agent.dir / "shared")
    script = render_hf_download("amasha", f"{root}/jobs/amasha/{NAME}", "/home/amasha",
                                repo_id="org/model", nfs_root=root,
                                dest=f"{root}/users/amasha/models/org--model")
    return {"folder_name": NAME, "script": script, **extra}


def _folder(agent, out):
    return agent.dir / out["folder"].removeprefix(str(agent.dir) + "/")


def test_the_token_is_written_0600_beside_the_script_and_not_into_it(jobs):  # noqa: F811
    out = jobs.call("job.submit", _payload(
        jobs, secret_file={"name": ".hf_token", "content": "hf_abc123"}))
    token = _folder(jobs, out) / ".hf_token"
    assert token.read_text() == "hf_abc123"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert "hf_abc123" not in (token.parent / "job.sbatch").read_text()


def test_no_token_means_no_token_file(jobs):  # noqa: F811
    out = jobs.call("job.submit", _payload(jobs))
    assert not (_folder(jobs, out) / ".hf_token").exists()


@pytest.mark.parametrize("secret", [{"name": "id_rsa", "content": "x"},
                                    {"name": ".hf_token", "content": "two words"},
                                    {"name": ".hf_token", "content": "a\nb"},
                                    {"name": ".hf_token", "content": ""},
                                    {"name": ".hf_token", "content": 5}, "token"])
def test_only_a_plain_token_file_is_accepted(jobs, secret):  # noqa: F811
    assert _err(jobs, "job.submit", _payload(jobs, secret_file=secret)).status == 422
