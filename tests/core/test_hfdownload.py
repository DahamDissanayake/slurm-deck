import inspect

import pytest

from sdcore.hfdownload import (
    AUTH_MESSAGE,
    TOKEN_FILE,
    parse_hf_result,
    render_hf_download,
    valid_repo_id,
)

SCRIPT = render_hf_download("amasha", "/shared/jobs/amasha/hf-x_1", "/home/amasha",
                            repo_id="meta-llama/Llama-3.1-8B", partition="gpu",
                            dest="/shared/users/amasha/models/meta-llama--Llama-3.1-8B",
                            revision="main")


def test_token_never_in_script():
    # The renderer is never given a token: it only names the file the token arrives in.
    assert "token" not in inspect.signature(render_hf_download).parameters
    assert [ln for ln in SCRIPT.splitlines() if "HF_TOKEN=" in ln] == [
        'if [ -f .hf_token ]; then HF_TOKEN="$(cat .hf_token)"; export HF_TOKEN; fi']


def test_token_file_is_removed_before_the_download_starts():
    def first(text):
        return SCRIPT.index(text)

    assert first("set +x") < first("cat .hf_token") < first(f"rm -f {TOKEN_FILE}")
    assert first(f"rm -f {TOKEN_FILE}") < first("snapshot_download")
    assert first("set +x") < first("export HF_HUB_DISABLE_XET=1")


def test_it_is_a_cpu_job_that_downloads_four_files_at_a_time():
    assert "#SBATCH --cpus-per-task=4" in SCRIPT and "#SBATCH --mem=8G" in SCRIPT
    assert "#SBATCH --time=08:00:00" in SCRIPT and "gres" not in SCRIPT
    assert "max_workers=4" in SCRIPT and "export HF_HUB_DISABLE_XET=1" in SCRIPT


def test_repo_and_destination_are_passed_as_quoted_environment_not_python_source():
    script = render_hf_download("a", "/f", "/home/a", repo_id="org/model",
                                dest="/d/my model; rm -rf /")
    assert "export SD_HF_DEST='/d/my model; rm -rf /'" in script
    assert "org/model" not in script.split("<<'PYEOF'")[1]   # not in the Python source


@pytest.mark.parametrize("repo", ["meta-llama/Llama-3.1-8B", "a/b", "org.x/model_1-2"])
def test_valid_repo_ids(repo):
    assert valid_repo_id(repo)


@pytest.mark.parametrize("repo", ["", "model", "a/b/c", "../x/y", "a/$(id)", "a/b;c", "a b/c",
                                  "/a/b", "a/-b", "a//b", "a/b\n"])
def test_invalid_repo_ids(repo):
    assert not valid_repo_id(repo)


def test_render_refuses_an_invalid_repo_id():
    with pytest.raises(ValueError):
        render_hf_download("a", "/f", "/home/a", repo_id="a/$(id)", dest="/d")


def test_results_are_read_from_the_job_output():
    assert parse_hf_result("starting\nSD_HF_DONE 12345\n") == ("done", 12345, "")
    state, size, message = parse_hf_result("SD_HF_FAIL auth\n")
    assert (state, size, message) == ("failed", None, AUTH_MESSAGE)
    missing = "HuggingFace has no repository with that name."
    assert parse_hf_result("SD_HF_FAIL not_found")[2] == missing
    assert parse_hf_result("SD_HF_FAIL boom")[2].startswith("The download failed")
    assert parse_hf_result("still going") == ("unknown", None, "")
