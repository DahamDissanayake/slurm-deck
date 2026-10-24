"""Environment verbs. Everything runs as the caller (kernel permissions on
top of the path checks here); only an admin deleting a shared environment
runs as sd-ops. Builds themselves are ordinary jobs (job.submit)."""

from __future__ import annotations

import json
import posixpath
import sys
from typing import Any

from deckagent.config import AgentConfig
from deckagent.identity import PosixIdentity, identity_for_user, ops_identity
from deckagent.protocol import AgentError, Caller, RequestContext
from deckagent.runas import run_as
from deckagent.verbs import files, verb
from sdcore.validate import user_browse_roots, user_job_root

PEOPLE = frozenset({"user", "admin"})
MARKER = ".sd-env-ok"
CHECK_S = 20

# Lists env folders (with their ready marker) and image files; run as the user.
_LIST = r"""
import json, os, sys
envs, images, marker = sys.argv[1:-2], sys.argv[-2], sys.argv[-1]
def names(d):
    try:
        return sorted(n for n in os.listdir(d) if not n.startswith("."))
    except OSError:
        return []
out = {"envs": [[d, n, os.path.exists(os.path.join(d, n, marker))]
                for d in envs for n in names(d) if os.path.isdir(os.path.join(d, n))],
       "images": [n for n in names(images) if n.endswith(".sif")]}
print(json.dumps(out))
"""

# Run with the env's own python: the script's top-level imports that this
# env can't find. Standard library and the script's own folder don't count.
_CHECK = r"""
import ast, importlib.util, json, sys
path = sys.argv[1]
with open(path, encoding="utf-8", errors="replace") as f:
    tree = ast.parse(f.read(), path)
names = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        names.update(a.name.split(".")[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
        names.add(node.module.split(".")[0])
std = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
sys.path.insert(0, path.rsplit("/", 1)[0] or "/")
print(json.dumps(sorted(n for n in names - std if importlib.util.find_spec(n) is None)))
"""


# Seams for tests: who the work runs as.
def _identity(caller: Caller, config: AgentConfig) -> PosixIdentity:
    return identity_for_user(caller, config)


def _ops_identity(caller: Caller, config: AgentConfig) -> PosixIdentity:
    return ops_identity(caller, config)


def _json(ident: PosixIdentity, argv: list[str], timeout: float = 30) -> Any:
    r = run_as(ident, argv, timeout=timeout)
    if r.returncode != 0:
        raise AgentError("env_check_failed",
                         r.stderr.decode(errors="replace").strip()[-300:] or "It didn't run.", 400)
    return json.loads(r.stdout)


def _under(path: str, roots: list[str]) -> bool:
    p = posixpath.normpath(path)
    return path.startswith("/") and any(p == r or p.startswith(r + "/") for r in roots)


def _refuse() -> AgentError:
    return AgentError("fs_refused", "That path is outside your areas.", 403)


def _env_roots(cfg: AgentConfig, user: str) -> tuple[str, str]:
    root = cfg.nfs_root.rstrip("/")
    return f"{root}/envs", f"{root}/users/{user}/envs"


@verb("env.list", allow=PEOPLE)
def env_list(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    cfg, user = ctx.config, str(ctx.caller.username)
    shared, mine = _env_roots(cfg, user)
    images = f"{cfg.nfs_root.rstrip('/')}/images"
    out = _json(_identity(ctx.caller, cfg),
                [sys.executable, "-I", "-c", _LIST, shared, mine, images, MARKER])
    lists: dict[str, list[dict[str, Any]]] = {"prebuilt": [], "mine": [], "images": []}
    for folder, name, ready in out["envs"]:
        kind = "prebuilt" if folder == shared else "mine"
        lists[kind].append({"name": name, "path": f"{folder}/{name}", "kind": kind,
                            "ready": bool(ready)})
    lists["images"] = [{"name": n, "path": f"{images}/{n}", "kind": "image", "ready": True}
                       for n in out["images"]]
    return lists


@verb("env.check_imports", allow=PEOPLE)
def check_imports(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """The packages a script imports that the environment doesn't have."""
    cfg, user = ctx.config, str(ctx.caller.username)
    env_path, script = str(payload.get("env_path", "")), str(payload.get("script_path", ""))
    reads = [*user_browse_roots(cfg.nfs_root, user), user_job_root(cfg.nfs_root, user)]
    if not _under(env_path, list(_env_roots(cfg, user))) or not _under(script, reads):
        raise _refuse()
    python = posixpath.normpath(env_path) + "/bin/python"
    missing = _json(_identity(ctx.caller, cfg), [python, "-I", "-c", _CHECK,
                                                 posixpath.normpath(script)], CHECK_S)
    return {"missing": missing}


@verb("env.delete", allow=PEOPLE)
def env_delete(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Users delete their own environments; admins (as_admin) shared ones."""
    cfg, caller = ctx.config, ctx.caller
    path = posixpath.normpath(str(payload.get("path", "")))
    shared, mine = _env_roots(cfg, str(caller.username))
    admin = payload.get("as_admin") is True
    if posixpath.dirname(path) != (shared if admin else mine):
        raise _refuse()
    if admin:
        ident, who = _ops_identity(caller, cfg), ["--user", str(caller.username), "--admin"]
    else:
        ident, who = _identity(caller, cfg), ["--user", str(caller.username)]
    return files._run(ident, files._argv(cfg, "delete", who, path, opts=("--recursive",)),
                      timeout=600)
