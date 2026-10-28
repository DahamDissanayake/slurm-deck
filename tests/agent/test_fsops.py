"""deckagent.fsops, run as a subprocess on a temp /shared tree as the current user."""

import io
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

if sys.platform != "linux":
    pytest.skip("fsops runs on Linux", allow_module_level=True)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for d in ("users/amasha/proj", "users/bob", "models/llama", "datasets", "jobs/amasha/j1",
              "envs", "data"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "users/bob/secret.txt").write_text("bob's")
    (tmp_path / "models/llama/config.json").write_text("{}")
    (tmp_path / "users/amasha/proj/train.py").write_text("print('hi')\n")
    return tmp_path


def fs(tree: Path, *args: str, stdin: bytes = b"", user: str = "amasha"):
    r = subprocess.run([sys.executable, "-m", "deckagent.fsops", args[0], "--user", user,
                        "--nfs-root", str(tree), *args[1:]], input=stdin, capture_output=True)
    return r


def js(r) -> dict:
    return json.loads(r.stdout)


def test_symlink_escape_refused(tree):
    os.symlink(tree / "users/bob", tree / "users/amasha/link")
    r = fs(tree, "list", "users/amasha/link")
    assert r.returncode == 2 and js(r)["ok"] is False
    assert fs(tree, "read", "users/amasha/link/secret.txt").returncode == 2
    assert fs(tree, "list", "users/bob").returncode == 2
    assert fs(tree, "list", "../../etc").returncode == 2


def test_list_and_stat(tree):
    (tree / "users/amasha/b.txt").write_text("12345")
    os.symlink("proj", tree / "users/amasha/ln")
    entries = js(fs(tree, "list", "users/amasha"))["entries"]
    assert [(e["name"], e["type"]) for e in entries] == [("proj", "dir"), ("b.txt", "file"),
                                                         ("ln", "link")]
    assert entries[1]["size"] == 5 and entries[1]["readonly"] is False
    shared = js(fs(tree, "list", "models"))["entries"]
    assert shared[0]["name"] == "llama" and shared[0]["readonly"] is True
    assert js(fs(tree, "list", "jobs/amasha"))["entries"][0]["name"] == "j1"
    st = js(fs(tree, "stat", "users/amasha/b.txt"))
    assert st["type"] == "file" and st["size"] == 5


def test_write_outside_own_area_refused(tree):
    for path in ("datasets/x.txt", "models/llama/x", "jobs/amasha/x", "users/bob/x"):
        assert fs(tree, "write", path, stdin=b"x").returncode == 2, path
    assert fs(tree, "mkdir", "datasets/new").returncode == 2
    assert fs(tree, "delete", "models/llama/config.json").returncode == 2
    assert (tree / "models/llama/config.json").exists()


def test_write_read_and_size_limit(tree):
    r = fs(tree, "write", "users/amasha/notes.md", "--max", "10", stdin=b"hello")
    assert r.returncode == 0, r.stderr
    assert fs(tree, "read", "users/amasha/notes.md").stdout == b"hello"
    assert fs(tree, "read", "users/amasha/notes.md", "--offset", "1", "--limit", "3").stdout \
        == b"ell"
    assert fs(tree, "write", "users/amasha/big", "--max", "4", stdin=b"hello").returncode == 2
    assert not (tree / "users/amasha/big").exists()


def test_mkdir_rename_delete(tree):
    assert fs(tree, "mkdir", "users/amasha/out").returncode == 0
    assert fs(tree, "rename", "users/amasha/proj/train.py", "users/amasha/out/t.py").returncode \
        == 0
    assert (tree / "users/amasha/out/t.py").exists()
    (tree / "users/amasha/other.py").write_text("")
    assert fs(tree, "rename", "users/amasha/other.py", "users/amasha/out/t.py").returncode == 2
    assert fs(tree, "delete", "users/amasha/out").returncode == 2        # not empty
    assert fs(tree, "delete", "users/amasha/out", "--recursive").returncode == 0
    assert fs(tree, "delete", "users/amasha", "--recursive").returncode == 2   # the root
    os.symlink(tree / "users/bob", tree / "users/amasha/tobob")
    assert fs(tree, "delete", "users/amasha/tobob").returncode == 0     # the link, not bob
    assert (tree / "users/bob/secret.txt").exists()


@pytest.mark.parametrize("name", ["a\nb", "a\rb", "a/b", "..", ".", "", "x" * 256])
def test_bad_new_names_refused(tree, name):
    # NUL can't reach argv at all; every other bad name is refused by the name rule.
    assert fs(tree, "mkdir", f"users/amasha/{name}").returncode != 0
    assert fs(tree, "stage-finalize", "upl12345", "users/amasha", name).returncode == 2
    assert sorted(p.name for p in (tree / "users/amasha").iterdir()) == ["proj"]


def test_unicode_and_spaces_roundtrip(tree):
    name = "données 50% #1.csv"
    assert fs(tree, "write", f"users/amasha/{name}", stdin=b"a,b").returncode == 0
    assert [e["name"] for e in js(fs(tree, "list", "users/amasha"))["entries"]] \
        == ["proj", name]
    assert fs(tree, "rename", f"users/amasha/{name}", "users/amasha/über.csv").returncode == 0
    assert (tree / "users/amasha/über.csv").read_text() == "a,b"


def test_stage_append_rejects_wrong_offset(tree):
    r = fs(tree, "stage-append", "upl12345", "--offset", "0", stdin=b"abc")
    assert (r.returncode, js(r)["size"]) == (0, 3)
    r = fs(tree, "stage-append", "upl12345", "--offset", "1", stdin=b"zz")
    assert r.returncode == 2 and js(r)["size"] == 3
    fs(tree, "stage-append", "upl12345", "--offset", "3", stdin=b"def")
    assert js(fs(tree, "stage-size", "upl12345"))["size"] == 6
    assert fs(tree, "stage-append", "../x", "--offset", "0").returncode == 2
    assert fs(tree, "stage-abort", "upl12345").returncode == 0
    assert js(fs(tree, "stage-size", "upl12345"))["size"] == 0


def test_finalize_refuses_existing_without_replace(tree):
    fs(tree, "stage-append", "upl12345", "--offset", "0", stdin=b"new")
    (tree / "users/amasha/data.bin").write_bytes(b"old")
    r = fs(tree, "stage-finalize", "upl12345", "users/amasha", "data.bin")
    assert r.returncode == 2 and js(r)["error"] == "A file with that name already exists."
    assert (tree / "users/amasha/data.bin").read_bytes() == b"old"
    r = fs(tree, "stage-finalize", "upl12345", "users/amasha", "data.bin", "--replace")
    assert r.returncode == 0 and (tree / "users/amasha/data.bin").read_bytes() == b"new"
    fs(tree, "stage-append", "upl99999", "--offset", "0", stdin=b"x")
    assert fs(tree, "stage-finalize", "upl99999", "datasets", "x").returncode == 2


def _zip(tree: Path, members: dict[str, bytes], symlink: str | None = None) -> str:
    path = tree / "users/amasha/a.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
    return "users/amasha/a.zip"


@pytest.mark.parametrize("member", ["../x", "/etc/passwd", "a/../../x"])
def test_extract_refuses_traversal(tree, member):
    arc = _zip(tree, {"ok.txt": b"fine", member: b"bad"})
    fs(tree, "mkdir", "users/amasha/out")
    r = fs(tree, "extract", arc, "users/amasha/out")
    assert r.returncode == 2
    assert list((tree / "users/amasha/out").iterdir()) == []      # nothing extracted at all


def test_extract_refuses_symlink_member(tree):
    arc = _zip(tree, {"ok.txt": b"fine"}, symlink="link")
    fs(tree, "mkdir", "users/amasha/out")
    assert fs(tree, "extract", arc, "users/amasha/out").returncode == 2
    assert list((tree / "users/amasha/out").iterdir()) == []
    tar = tree / "users/amasha/a.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        info = tarfile.TarInfo("ln")
        info.type, info.linkname = tarfile.SYMTYPE, "/etc"
        t.addfile(info)
    assert fs(tree, "extract", "users/amasha/a.tar.gz", "users/amasha/out").returncode == 2


def test_extract_zip_and_tar(tree):
    arc = _zip(tree, {"d/one.txt": b"1", "two.txt": b"22"})
    fs(tree, "mkdir", "users/amasha/out")
    assert fs(tree, "extract", arc, "users/amasha/out").returncode == 0
    assert (tree / "users/amasha/out/d/one.txt").read_bytes() == b"1"
    with tarfile.open(tree / "users/amasha/b.tgz", "w:gz") as t:
        data = b"tar data"
        info = tarfile.TarInfo("t/x.bin")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    assert fs(tree, "extract", "users/amasha/b.tgz", "users/amasha/out").returncode == 0
    assert (tree / "users/amasha/out/t/x.bin").read_bytes() == b"tar data"
    assert fs(tree, "extract", arc, "datasets").returncode == 2           # read-only dest
    assert fs(tree, "extract", arc, "users/amasha/out").returncode == 2  # would overwrite


def _bomb(tree: Path) -> str:
    """A tiny zip that declares 64 MiB of zeros."""
    path = tree / "users/amasha/bomb.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ok.txt", b"fine")
        z.writestr("zeros.bin", b"\0" * (64 * 1024 * 1024))
    assert path.stat().st_size < 1024 * 1024
    return "users/amasha/bomb.zip"


def test_extract_refuses_bomb_over_cap(tree):
    arc = _bomb(tree)
    fs(tree, "mkdir", "users/amasha/out")
    r = fs(tree, "extract", "--max-bytes", str(1024 * 1024), arc, "users/amasha/out")
    assert r.returncode == 2 and "too large" in js(r)["error"]
    assert list((tree / "users/amasha/out").iterdir()) == []      # nothing extracted at all


def test_extract_refuses_bomb_over_free_space(tree):
    arc = _bomb(tree)
    fs(tree, "mkdir", "users/amasha/out")
    free = os.statvfs(tree).f_bavail * os.statvfs(tree).f_frsize
    # A margin that leaves less than 64 MiB free makes the declared size too big.
    r = fs(tree, "extract", "--margin", str(max(free - 1024 * 1024, 0)), arc, "users/amasha/out")
    assert r.returncode == 2 and "free space" in js(r)["error"]
    assert list((tree / "users/amasha/out").iterdir()) == []
    r = fs(tree, "extract", "--max-bytes", str(65 * 1024 * 1024), arc, "users/amasha/out")
    assert r.returncode == 0, r.stdout
    assert (tree / "users/amasha/out/zeros.bin").stat().st_size == 64 * 1024 * 1024


def test_copy_member_stops_past_declared_size(tmp_path):
    from deckagent.fsops import Refused, _copy_member
    out = tmp_path / "m"
    with pytest.raises(Refused):
        _copy_member(io.BytesIO(b"x" * 10), str(out), declared=4, name="m")
    assert not out.exists()                                        # partial file removed
    _copy_member(io.BytesIO(b"abcd"), str(out), declared=4, name="m")
    assert out.read_bytes() == b"abcd"


def test_zipstream_is_a_valid_zip(tree):
    (tree / "users/amasha/proj/sub").mkdir()
    (tree / "users/amasha/proj/sub/w.bin").write_bytes(b"\x00" * 3000)
    os.symlink(tree / "users/bob/secret.txt", tree / "users/amasha/proj/leak")
    r = fs(tree, "zipstream", "users/amasha/proj")
    assert r.returncode == 0, r.stderr
    z = zipfile.ZipFile(io.BytesIO(r.stdout))
    assert sorted(z.namelist()) == ["proj/sub/", "proj/sub/w.bin", "proj/train.py"]
    assert z.read("proj/sub/w.bin") == b"\x00" * 3000 and z.testzip() is None
    one = zipfile.ZipFile(io.BytesIO(fs(tree, "zipstream", "users/amasha/proj/train.py").stdout))
    assert one.namelist() == ["train.py"]


def test_du(tree):
    (tree / "users/amasha/proj/w.bin").write_bytes(b"x" * 1000)
    assert js(fs(tree, "du", "users/amasha"))["bytes"] >= 1000 + 12
