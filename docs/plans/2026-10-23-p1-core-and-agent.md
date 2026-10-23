# Phase 1 — Core and deck-agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the new repo's foundation: the shared pure-logic package `sdcore` (ported from `legacy/v1.4-tui`), the root **deck-agent** service on the login node with its session check, run-as-user mechanism, audit log and cluster + account verbs, the **GPU-host helper**, and the web side's `AgentClient`.

**Architecture:** deck-agent is an HTTP/1.1 server on a Unix socket (stdlib `http.server`), accepting only the `sdweb` and `sdworker` UIDs. It resolves every request to a `Caller` from a read-only Postgres view, decides which Linux identity may be used, and runs user work through `subprocess` with `user=`/`group=`/`extra_groups=`. Root-on-disk steps on the GPU host go through one forced-command script over SSH.

**Tech Stack:** Python ≥ 3.11 stdlib, psycopg 3, httpx (client side), pytest.

**Spec:** `docs/specs/2026-10-23-web-platform-design.md` §3, §4.1–4.4, §5.2, §5.5, §5.7, §10. **Roadmap:** `docs/plans/2026-10-23-web-platform-roadmap.md` (layout, shared names, protocol, global constraints).

## Global Constraints

- Everything in the roadmap's "Global constraints" and "Shared names" sections.
- Port from `legacy/v1.4-tui`, don't rewrite: copy the named functions with their legacy tests (`git show legacy/v1.4-tui:<path>`), then adapt.
- `sdcore` does no I/O beyond reading files it is handed paths to; no `subprocess`, no env lookups at import time.
- Username rule: `^[a-z_][a-z0-9_-]{0,31}$`, and never one of the reserved names (Task 3).
- deck-agent must never terminate on a bad request: every handler exception becomes a JSON error.

## Review Focus

- **A request body that isn't a JSON object** (`"x"`, `[1,2]`, `{"username": 5}`) — the legacy daemon died on all three; deck-agent must answer 400 and keep serving. Test in Task 5.
- **A slow client trickling bytes** — must not hold a worker forever; whole-request deadline 30 s. Test in Task 5.
- **A session that is valid in the DB but whose account was disabled a second ago** — must be refused (status check on every call). Test in Task 6.
- **Usernames that resolve outside `/shared/users`** (`.`, `..`, `a/b`, empty, `root`, `slurmadmin`) reaching delete/purge — refused before any command runs. Tests in Tasks 3 and 8.
- **Act-as pointing at a sysadmin or shell user** — refused even for an admin session. Test in Task 7.

---

### Task 1: Repository scaffold and CI

**Files:**
- Create: `.gitattributes`, `pyproject.toml`, `src/sdcore/__init__.py`, `src/deckagent/__init__.py`, `src/sdweb/__init__.py`, `tests/conftest.py`, `tests/core/test_smoke.py`, `.github/workflows/ci.yml`
- Modify: `.gitignore` (replace legacy entries with: Python caches, venvs, `node_modules/`, `frontend/dist/`, `*.env` except `*.env.example`, `site.env`, `secrets.env`, `.pytest_cache/`, `.coverage`)

**Interfaces:**
- Produces: installable project `slurm-deck-web` with extras `[web]` (fastapi, uvicorn[standard], sqlalchemy>=2, alembic, psycopg[binary]>=3.1, argon2-cffi, httpx), `[agent]` (psycopg[binary]>=3.1), `[dev]` (pytest, pytest-asyncio, httpx). Pytest markers `root` (needs real root + `useradd`) and `pg` (needs `TEST_DATABASE_URL`); both skip cleanly when unavailable.

- [ ] **Step 1:** Write `tests/core/test_smoke.py::test_packages_import` asserting `import sdcore, deckagent, sdweb` works and each has `__version__ == "2.0.0.dev0"`.
- [ ] **Step 2:** Run `pytest -q` → FAIL (no packages).
- [ ] **Step 3:** Create the files above. `.gitattributes`: `* text=auto eol=lf`. `conftest.py`: register markers; `root` skips unless `os.geteuid() == 0 and shutil.which("useradd")`; `pg` skips unless `TEST_DATABASE_URL` is set.
- [ ] **Step 4:** CI workflow: on `pull_request` and `push` to `dev`/`main`; job `python` on `ubuntu-latest`, Python 3.11 and 3.12 matrix, Postgres 16 service, `pip install -e .[web,agent,dev]`, run `pytest -q -m "not root"`, then `sudo -E env PATH=$PATH pytest -q -m root`.
- [ ] **Step 5:** Run `pytest -q` → PASS.
- [ ] **Step 6:** Commit `<KEY>: scaffold repo, packages and CI`.

---

### Task 2: `sdcore.slurmparse` and `sdcore.pods`

**Files:**
- Create: `src/sdcore/slurmparse.py`, `src/sdcore/pods.py`, `tests/core/test_slurmparse.py`, `tests/core/test_pods.py`
- Source: `legacy/v1.4-tui:slurmdeck/slurm.py` (`NodeStats`, `QueueEntry`, `_tres_value`, the parsing inside `get_node_stats`, `queue`, `sacct_history`, `_read_gpu_stats_file`), `slurmdeck/pods.py` (whole file), `tests/test_pods.py`, `tests/test_slurm.py`.

**Interfaces:**
- Produces:
  - `NodeStats`, `QueueEntry` dataclasses — legacy fields unchanged, plus `QueueEntry.pods: int = 0` and `QueueEntry.time_left_s: int | None = None`.
  - `parse_scontrol_node(text: str) -> NodeStats | None`
  - `merge_gpu_stats(stats: NodeStats, gpu_json: dict | None, now: float, max_age_s: int = 10, mtime: float | None = None) -> NodeStats` (sets `live_stats` only when fresh)
  - `SQUEUE_FORMAT: str` = `"%i|%j|%u|%T|%P|%M|%l|%D|%b|%L"`; `parse_squeue(text: str) -> list[QueueEntry]`
  - `SACCT_FORMAT: str` = `"JobID,JobName,User,State,Elapsed,Start,End,AllocTRES,ExitCode"`; `parse_sacct(text: str) -> list[QueueEntry]` (drops step lines like `123.batch`, strips `CANCELLED by 1234` → `CANCELLED`, keeps terminal states only)
  - `parse_slurm_duration(text: str) -> int | None` (`"1-02:03:04"`, `"02:03:04"`, `"03:04"`, `"UNLIMITED"`→None, `"INVALID"`→None)
  - pods: `pod_count`, `pod_count_known`, `pod_resources`, `resources_for`, `estimated_vram_gb`, `fits_new_pod_count` — legacy signatures, importing `NodeStats` from `sdcore.slurmparse`.

- [ ] **Step 1:** Port legacy pod tests unchanged (import path only). Add:
  ```python
  def test_parse_squeue_reads_pods_and_time_left():
      line = "42|nb_1|amasha|RUNNING|gpu|1:00:00|8:00:00|1|gres/shard:2|7:00:00"
      e = parse_squeue(line)[0]
      assert (e.job_id, e.user, e.state, e.pods, e.time_left_s) == ("42", "amasha", "RUNNING", 2, 25200)
  def test_parse_sacct_strips_steps_and_suffixes():
      text = "10|a|u|CANCELLED by 1500|0:05|...|...|...|0:0\n10.batch|batch|u|CANCELLED|0:05|...|...|...|0:15"
      rows = parse_sacct(text)
      assert [r.state for r in rows] == ["CANCELLED"]
  def test_parse_slurm_duration():
      assert parse_slurm_duration("1-02:03:04") == 93784
      assert parse_slurm_duration("03:04") == 184
      assert parse_slurm_duration("UNLIMITED") is None
  def test_stale_gpu_stats_ignored():
      s = merge_gpu_stats(base_stats(), {"gpu_util": 90}, now=1000.0, mtime=980.0)
      assert s.live_stats is False and s.gpu_util == 0
  ```
- [ ] **Step 2:** `pytest tests/core -q` → FAIL.
- [ ] **Step 3:** Implement by moving legacy parsing out of the subprocess-calling functions; `%b` gives `gres/shard:N` (or `N/A` → 0 pods).
- [ ] **Step 4:** `pytest tests/core -q` → PASS.
- [ ] **Step 5:** Commit `<KEY>: port Slurm output parsing and pod sizing into sdcore`.

---

### Task 3: `sdcore.validate` and `sdcore.names`

**Files:**
- Create: `src/sdcore/validate.py`, `src/sdcore/names.py`, `tests/core/test_validate.py`, `tests/core/test_names.py`
- Source: `legacy/v1.4-tui:slurmdeck/validate.py`, `tests/test_validate.py`.

**Interfaces:**
- Produces:
  - `names.USERNAME_RE` = `^[a-z_][a-z0-9_-]{0,31}$`; `names.RESERVED: frozenset[str]` = root, daemon, bin, sys, nobody, slurm, slurmadmin, munge, mysql, postgres, sshd, sdweb, sdworker, sd-ops, sdprov, public, shared, admin, gpuusers, gpuadmins, webusers, docker, sudo; `names.valid_username(name: str) -> bool`; `names.suggest_username(email: str, taken: set[str]) -> str` (local part, lowercased, invalid chars → `-`, leading digit prefixed `u`, truncated to 32, `-2`, `-3`… on collision).
  - validate (legacy names, but **no env lookups at import**; limits passed in): `clean_time_limit(value: str, max_hours: int) -> str | None`, `clean_job_name`, `clean_run_command`, `clean_array_spec`, `clean_dependency`, `user_browse_roots(nfs_root, username)`, `user_upload_root`, `user_job_root`, `in_user_browse_jail`, `in_user_upload_jail`, `in_user_job_jail`, `validate_sbatch(text: str, username: str) -> list[str]`, `validate_against_qos(gpu_shards: int, time_limit: str, max_pods: int | None, max_hours: int | None) -> tuple[bool, str]`, `parse_hms(value: str) -> int | None`.

- [ ] **Step 1:** Port legacy validate tests. Add:
  ```python
  @pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "Root", "root", "slurmadmin", "9abc", "x"*33, "sdweb"])
  def test_invalid_usernames(bad): assert not valid_username(bad)
  def test_suggest_username():
      assert suggest_username("Amasha.Perera@iit.ac.lk", set()) == "amasha-perera"
      assert suggest_username("amasha@x.com", {"amasha"}) == "amasha-2"
      assert suggest_username("123@x.com", set()) == "u123"
  def test_clean_time_limit_caps_to_given_max():
      assert clean_time_limit("30:00:00", max_hours=24) == "24:00:00"
  def test_browse_jail_rejects_symlink_escape(tmp_path): ...  # link inside user dir pointing at another user's dir → False
  ```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: port input validation and add username rules`.

---

### Task 4: `sdcore.launchspec` and `sdcore.sbatch` (batch jobs)

**Files:**
- Create: `src/sdcore/launchspec.py`, `src/sdcore/sbatch.py`, `tests/core/test_launchspec.py`, `tests/core/test_sbatch.py`
- Source: `legacy/v1.4-tui:slurmdeck/launchspec.py`, `slurmdeck/jobs.py` (`JobSpec`, `TaskDefaults`, `resource_defaults`, `gres_directive`, `render_sbatch`, `pip_install_block`), their tests.

**Interfaces:**
- Produces:
  - `LaunchSpec` (legacy fields; `time_limit` default `"08:00:00"`), `default_spec(intent: str, stats: NodeStats | None, default_time: str = "08:00:00") -> LaunchSpec` with intents `notebook`, `batch`, `terminal`, `smoke`; `apply_pods`, `from_template(tdata: dict, stats) -> LaunchSpec`, `from_rerun(parsed: dict, script: str, stats) -> LaunchSpec`.
  - `JobSpec` (legacy fields minus the `getpass` default — `user` is required), `to_job_spec(ls, *, user, partition, job_name, run_command) -> JobSpec`.
  - `gres_directive(gpu_shards: int) -> str` (`"shard:2"`), `pip_install_block(requirements: str, packages: str) -> str`.
  - `render_batch(spec: JobSpec, folder: str, home: str, mail_types: str) -> str` — legacy `render_sbatch` plus: `#SBATCH --export=NONE`; `export HOME=<home>`, `export USER=<user>`, `export PATH=/usr/local/bin:/usr/bin:/bin` before any activation; `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` when `gpu_shards > 0`; `#SBATCH --mail-user`/`--mail-type` only when `spec.mail_user`.
  - `job_folder_name(job_name: str, now: datetime) -> str` → `f"{job_name}_{now:%Y%m%d_%H%M%S}"`.

- [ ] **Step 1:** Port legacy tests for the ported functions. Add:
  ```python
  def test_batch_sets_clean_env_and_home():
      s = render_batch(spec(user="amasha"), "/shared/jobs/amasha/t_1", home="/home/amasha", mail_types="END,FAIL")
      assert "#SBATCH --export=NONE" in s and "export HOME=/home/amasha" in s
      assert s.index("export HOME=") < s.index("conda activate")
  def test_batch_sets_alloc_conf_only_with_gpu():
      assert "expandable_segments:True" in render_batch(spec(gpu_shards=1), ...)
      assert "expandable_segments" not in render_batch(spec(gpu_shards=0), ...)
  def test_default_time_is_eight_hours():
      assert default_spec("notebook", None).time_limit == "08:00:00"
  ```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: port launch spec and batch sbatch rendering`.

---

### Task 5: deck-agent server and protocol

**Files:**
- Create: `src/deckagent/config.py`, `src/deckagent/protocol.py`, `src/deckagent/server.py`, `src/deckagent/verbs/__init__.py`, `src/deckagent/__main__.py`, `tests/agent/test_server.py`

**Interfaces:**
- Produces:
  - `AgentConfig` (frozen dataclass) loaded by `load_config(env: Mapping[str, str]) -> AgentConfig` from `SD_AGENT_SOCKET`, `SD_DB_RO_URL`, `SD_NFS_ROOT` (`/shared`), `SD_WEB_UID`, `SD_WORKER_UID`, `SD_WEBUSERS_GROUP` (`webusers`), `SD_GPUUSERS_GROUP` (`gpuusers`), `SD_ADMIN_GROUP` (`gpuadmins`), `SD_OPS_USER` (`sd-ops`), `SD_SLURM_BIN` (`/usr/bin`), `SD_PARTITION` (`gpu`), `SD_COMPUTE_NODE`, `SD_STATS_FILE`, `SD_GPU_HELPER_SSH`, `SD_GPU_HELPER_KEY`, `SD_GRANT_KEY_FILE`, `SD_AUDIT_LOG`, `SD_WEB_UID_MIN` (20000), `SD_WEB_UID_MAX` (59999), `SD_MAX_WORKERS` (8), `SD_REQUEST_DEADLINE_S` (30), `SD_MAX_JSON_BYTES` (1 MiB).
  - `AgentError(code: str, message: str, status: int)`.
  - `verb(name: str, *, allow: frozenset[str], body: str = "json")` decorator registering `handler(ctx: RequestContext, payload: dict | BinaryIO) -> Any`; `allow` ⊆ {`"user"`, `"admin"`, `"worker"`}.
  - `RequestContext(caller: Caller, config: AgentConfig, headers: Mapping[str, str])` (`Caller` from Task 6).
  - `AgentServer(config, store: SessionStore)` with `serve_forever()`, `shutdown()`; `python -m deckagent` runs it.
- Behaviour: `socketserver.ThreadingMixIn` over `AF_UNIX` with a `BoundedSemaphore(max_workers)`; socket file mode `0660`, group = the group of `sdweb` (installer sets); each connection checks `SO_PEERCRED` uid ∈ {web_uid, worker_uid} else closes with 403; whole-request deadline via `socket.settimeout` plus a monotonic budget checked between reads; JSON bodies must decode to a `dict` with ≤ `max_json_bytes`; unknown verb → 404 `unknown_verb`; any unexpected exception → 500 `internal` with the exception logged, never re-raised.

- [ ] **Step 1:** Write tests running a real `AgentServer` on a tmp socket with a fake `SessionStore` and a registered test verb `echo`:
  ```python
  @pytest.mark.parametrize("body", [b'"x"', b"[1,2]", b"not json"])
  def test_non_object_body_is_400_and_server_survives(agent, body):
      assert post(agent, "echo", raw=body).status_code == 400
      assert post(agent, "echo", json={"a": 1}).json() == {"ok": True, "data": {"a": 1}}
  def test_handler_exception_is_500_and_server_survives(agent): ...  # verb "boom" raises ValueError
  def test_unknown_verb_404(agent): ...
  def test_slow_client_is_cut_off(agent):  # send headers then 1 byte every 2 s; deadline set to 3 s in fixture
      ...; assert elapsed < 6
  def test_slow_request_does_not_block_fast_one(agent):  # verb "sleep" sleeps 2 s in a thread; "echo" returns in < 0.5 s meanwhile
  def test_wrong_peer_uid_refused(agent_with_uids_excluding_me): ...  # 403
  ```
- [ ] **Step 2:** `pytest tests/agent/test_server.py -q` → FAIL.
- [ ] **Step 3:** Implement `config.py`, `protocol.py` (error envelope, `json_response`, `read_json_body`), `server.py`, `__main__.py`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add deck-agent socket server with bounded workers and safe errors`.

---

### Task 6: Session resolution (`deckagent.sessions`)

**Files:**
- Create: `src/deckagent/sessions.py`, `tests/agent/test_sessions.py`

**Interfaces:**
- Consumes: `AgentConfig` (Task 5).
- Produces:
  - `SessionRow(username: str, role: str, linux_kind: str, uid: int | None, status: str, created_at: datetime, last_seen_at: datetime, acting_as_username: str | None)`.
  - `SessionStore` protocol: `lookup(token_hash: str) -> SessionRow | None`; `account(username: str) -> SessionRow | None` (status/role/kind of an account, used for act-as targets).
  - `PgSessionStore(dsn: str)` reading the view **`agent_sessions`** and **`agent_accounts`** (Phase 2 creates both; columns exactly the `SessionRow` fields plus `token_hash` for `agent_sessions`).
  - `hash_token(raw: str) -> str` = SHA-256 hex. (Phase 2 stores the same hash.)
  - `Caller(username: str | None, role: str, linux_kind: str | None, is_worker: bool, acting_admin: str | None)`; `role` ∈ {`user`, `admin`, `worker`}.
  - `resolve_caller(peer_uid: int, headers: Mapping[str, str], store: SessionStore, config: AgentConfig, now: datetime, idle_minutes: int = 30, max_hours: int = 12) -> Caller` raising `AgentError("no_session", ..., 401)`.
- Rules: peer = worker uid → `Caller(None, "worker", None, True, None)` and session header ignored. Otherwise header `X-SD-Session` required; row must exist, `status == "active"`, `now - last_seen_at ≤ idle`, `now - created_at ≤ max`. If `acting_as_username` is set: the session's own role must be `admin`; the target account must exist, be active, and not be `linux_kind == "shell"`; the Caller becomes the target (`role` of the target) with `acting_admin = <admin username>`.

- [ ] **Step 1:** Tests with a dict-backed fake store:
  ```python
  def test_expired_idle_session_refused(): ...      # last_seen 31 min ago → 401
  def test_absolute_cap_refused(): ...               # created 12h01m ago, last_seen 1 min ago → 401
  def test_disabled_account_refused(): ...           # status "disabled" → 401
  def test_worker_uid_gets_worker_caller(): ...
  def test_act_as_requires_admin(): ...              # user session with acting_as → 403
  def test_act_as_shell_target_refused(): ...        # 403
  def test_act_as_resolves_target_and_records_admin():
      c = resolve_caller(...); assert (c.username, c.acting_admin) == ("amasha", "dinuka")
  @pytest.mark.pg
  def test_pg_store_reads_view(pg_conn): ...         # creates the two views on tmp tables matching the spec'd columns
  ```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: resolve deck-agent callers from read-only session views`.

---

### Task 7: Identity rules, run-as and local audit

**Files:**
- Create: `src/deckagent/identity.py`, `src/deckagent/runas.py`, `src/deckagent/audit.py`, `tests/agent/test_identity.py`, `tests/agent/test_runas.py`, `tests/agent/test_audit.py`

**Interfaces:**
- Consumes: `Caller` (Task 6), `names.valid_username`, `names.RESERVED` (Task 3).
- Produces:
  - `PosixIdentity(name: str, uid: int, gid: int, groups: tuple[int, ...], home: str)`.
  - `identity_for_user(caller: Caller, config: AgentConfig, pw=pwd, gr=grp) -> PosixIdentity` — allowed only if `caller.username` is a valid, non-reserved name and either (a) the account is a member of `webusers`, or (b) `caller.linux_kind == "shell"` and the account is **not** in `sudo`, `gpuadmins`, or `admin`, and uid ≥ 1000. Never uid 0, never `SD_OPS_USER`. Else `AgentError("identity_refused", ..., 403)`.
  - `ops_identity(config) -> PosixIdentity` for `sd-ops`; only callable from handlers whose caller role is `admin`.
  - `run_as(ident: PosixIdentity, argv: list[str], *, input: bytes | None = None, timeout: float = 60, cwd: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess[bytes]` — `subprocess.run(..., user=ident.uid, group=ident.gid, extra_groups=list(ident.groups), env=env or {"HOME": ident.home, "USER": ident.name, "PATH": "/usr/local/bin:/usr/bin:/bin"}, stdin=DEVNULL unless input, close_fds=True)`.
  - `popen_as(ident, argv, **kw) -> subprocess.Popen[bytes]` for streaming.
  - `audit(config, *, actor: str | None, acting_admin: str | None, verb: str, target: str = "", detail: dict | None = None, result: str) -> None` — appends one JSON line to `SD_AUDIT_LOG` (`ts` ISO-8601 UTC), file created `0600`; never raises (logs on failure).
  - The server (Task 5) calls `audit(...)` after every verb with `result` ∈ {`ok`, `<error code>`}.

- [ ] **Step 1:** Tests:
  ```python
  def test_root_never_allowed(): ...                         # fake pwd returns uid 0 → 403
  def test_reserved_name_refused(): ...                      # "slurmadmin" → 403
  def test_webuser_allowed(): ...                            # fake grp: webusers has "amasha"
  def test_shell_user_in_sudo_refused(): ...
  @pytest.mark.root
  def test_run_as_really_drops_privileges(tmp_user):        # creates a throwaway user
      r = run_as(tmp_user, ["id", "-u"]); assert r.stdout.strip() == str(tmp_user.uid).encode()
  def test_audit_line_written_and_mode_0600(tmp_path): ...
  def test_server_audits_each_verb(agent): ...               # echo call → one line with verb "echo", result "ok"
  ```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run (`pytest tests/agent -q`, and `sudo -E pytest -m root tests/agent`) → PASS.
- [ ] **Step 5:** Commit `<KEY>: add identity rules, run-as-user and agent audit log`.

---

### Task 8: GPU-host helper and its client

**Files:**
- Create: `gpuhost/sd-gpu-helper`, `src/deckagent/gpuhost.py`, `tests/gpuhost/test_helper.py`, `tests/agent/test_gpuhost_client.py`, `deploy/cluster/gpuhost/authorized_keys.example`, `deploy/cluster/gpuhost/sudoers-sdprov`
- Source for logic: `legacy/v1.4-tui:deploy/slurm-deck-adduser.sh` steps 3 and 5, `deploy/slurm-deck-deluser.sh` data handling.

**Interfaces:**
- Produces:
  - `sd-gpu-helper` reads `SSH_ORIGINAL_COMMAND` (or argv for tests), accepts exactly:
    `create-account <user> <uid>`, `create-folders <user> <uid>`, `folder-info <user>`, `archive <user>`, `purge <user>`, `delete-account <user>`, `ping`. Prints one JSON object on stdout; exit 0 on success, 2 on refusal, 1 on failure.
    - Every `<user>` must pass the Task 3 username rule (inlined copy: the helper is stdlib-only and standalone); `<uid>` must be an int in `[1000, 60000]` and must not belong to a different existing account.
    - `create-account`: `groupadd -g uid user`; `useradd -u uid -g uid -m -d /home/<user> -s /usr/sbin/nologin -G <webusers>,<gpuusers> user`; `passwd -l user`; re-own `/home/<user>` to `uid:uid`.
    - `create-folders`: `$NFS_ROOT/users/<user>` and `$NFS_ROOT/jobs/<user>` → owner `uid:<admin group>`, mode `2770`, `setfacl -R -m g:<admin>:rwX -m d:g:<admin>:rwx`.
    - `folder-info`: `{"exists": bool, "owner_uid": int, "bytes": int, "mtime": iso}` for `users/<user>` (bytes from `du -sb`).
    - `archive`: rename `users/<user>` → `users/<user>.offboarded` (an existing `.offboarded` is first renamed with a timestamp suffix, never deleted).
    - `purge`: `rm -rf --one-file-system` on `users/<user>` and `jobs/<user>` only after re-checking each resolved path's parent is exactly `$NFS_ROOT/users` / `$NFS_ROOT/jobs`.
    - `delete-account`: `pkill -KILL -u user`; `userdel user`; `groupdel user`; verify `id user` fails.
    - Config from `/etc/slurm-deck-web/gpu-helper.env` (`NFS_ROOT`, `WEBUSERS_GROUP`, `GPUUSERS_GROUP`, `ADMIN_GROUP`); a `--root` override for tests.
  - `sudoers-sdprov`: `sdprov ALL=(root) NOPASSWD: /usr/local/sbin/sd-gpu-helper` (no arguments wildcard; args arrive via `SSH_ORIGINAL_COMMAND`, preserved with `Defaults!/usr/local/sbin/sd-gpu-helper env_keep += "SSH_ORIGINAL_COMMAND"`).
  - `authorized_keys.example`: `restrict,command="sudo /usr/local/sbin/sd-gpu-helper" ssh-ed25519 AAAA... deck-agent`.
  - `GpuHost(config)` in `deckagent.gpuhost` with methods `create_account(user, uid) -> None`, `create_folders(user, uid) -> None`, `folder_info(user) -> FolderInfo`, `archive(user) -> None`, `purge(user) -> None`, `delete_account(user) -> None`, `ping() -> bool`; runs `ssh -i <key> -o BatchMode=yes -o StrictHostKeyChecking=yes <SD_GPU_HELPER_SSH> <op> <args>`; maps exit 2 → `AgentError("gpuhost_refused", 403)`, other non-zero → `AgentError("gpuhost_failed", 502)`.

- [ ] **Step 1:** Helper tests (run the script with `--root tmp_path --dry-run` where commands are printed, not run):
  ```python
  @pytest.mark.parametrize("cmd", ["purge ..", "purge .", "purge a/b", "archive root", "create-account x 0",
                                   "create-account x abc", "rm -rf /", "purge amasha; id", ""])
  def test_refuses_bad_commands(cmd): assert run_helper(cmd).returncode == 2
  def test_purge_refuses_symlinked_user_dir(tmp_path): ...      # users/amasha -> /etc  → 2
  def test_archive_never_deletes_previous_archive(tmp_path): ... # existing amasha.offboarded is renamed, not removed
  def test_folder_info_reports_owner_and_size(tmp_path): ...
  ```
  Client tests with a fake `ssh` on PATH echoing canned JSON / exit codes.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add forced-command GPU-host helper and its agent client`.

---

### Task 9: Cluster and account verbs, `AgentClient`, systemd unit

**Files:**
- Create: `src/deckagent/verbs/cluster.py`, `src/deckagent/verbs/accounts.py`, `src/deckagent/slurmcmd.py`, `src/sdweb/agent.py`, `deploy/systemd/deck-agent.service`, `deploy/agent.env.example`, `tests/agent/test_verbs_cluster.py`, `tests/agent/test_verbs_accounts.py`, `tests/web/test_agent_client.py`, `tests/agent/fakebin/` (fake `scontrol`, `squeue`, `sacct`, `sacctmgr`, `scancel`, `sbatch`, `df`, `useradd`, `groupadd`, `userdel`, `groupdel`, `passwd`, `pkill`, `ssh`)

**Interfaces:**
- Consumes: Tasks 2, 3, 5–8.
- Produces (verbs; `allow` in brackets):
  - `cluster.status` [user, admin, worker] → `{"node": NodeStats-as-dict, "pods_total": int, "pods_used": int, "partition_max_s": int | None}`; reads `scontrol show node <SD_COMPUTE_NODE>`, `scontrol show partition <SD_PARTITION>`, and the stats file.
  - `cluster.queue` [user, admin, worker] → `{"jobs": [{"job_id","user","state","pods","time_used","time_limit","time_left_s"}]}` — no job names or paths for non-admin callers (`name` included only when caller is admin or the job's owner).
  - `cluster.disk_free` [user, admin, worker] → `{"total_bytes","used_bytes","free_bytes"}` via `os.statvfs(SD_NFS_ROOT)`.
  - `job.time_left_all` [worker] → `{"jobs": [{"job_id","user","time_left_s","state"}]}` for RUNNING jobs.
  - `account.inspect_folder` [admin] `{"username"}` → `FolderInfo` plus `"uid_in_use": bool` (uid present in login-node passwd).
  - `account.create` [admin] `{"username","uid","link_existing": bool}` → creates login-node account (`groupadd -g uid`, `useradd -u uid -g uid -M -d /home/<u> -s /usr/sbin/nologin -G webusers,gpuusers`, `passwd -l`), `sacctmgr -i add user <u> account=<SD_SLURM_ACCOUNT default "default"> qos=<SD_SLURM_QOS default "normal">`, then `GpuHost.create_account` and `create_folders` (skipped for folders when `link_existing`). Refuses: invalid/reserved name (422), uid outside `[SD_WEB_UID_MIN, SD_WEB_UID_MAX]` unless `link_existing` and the uid equals `folder_info.owner_uid` and is ≥ 1000 and not in passwd (409), username already in passwd (409). On a failure after partial creation it rolls back what it created and reports `account_create_failed`.
  - `account.attach_shell` [admin] `{"username"}` → checks the existing login-node account is a shell user (not in `webusers`/`sudo`/`gpuadmins`, uid ≥ 1000) and returns `{"uid": int}`; changes nothing.
  - `account.delete` [admin] `{"username","purge": bool}` → `scancel -u`, `sacctmgr -i delete user`, `GpuHost.archive` or `purge`, `GpuHost.delete_account`, then login-node `pkill`/`userdel`/`groupdel`; refuses reserved names and accounts not in `webusers`.
  - `slurmcmd.run_slurm(config, args: list[str], *, as_ident: PosixIdentity | None = None, timeout: float = 15) -> str` (root when `as_ident` is None; raises `AgentError("slurm_failed", 502)` with stderr).
  - `sdweb.agent.AgentClient(socket_path: str, timeout: float = 30)` with `call(verb: str, payload: dict | None = None, *, session: str | None = None) -> Any` (raises `AgentCallError(code, message, status)`), `stream(verb, payload, *, session) -> Iterator[bytes]`, `upload_chunk(upload_id: str, offset: int, data: Iterable[bytes], *, grant: str) -> int`. Uses `httpx.Client(transport=httpx.HTTPTransport(uds=socket_path))`.
  - `deck-agent.service`: `User=root`, `ExecStart=/opt/slurm-deck-web/agent-venv/bin/python -m deckagent`, `EnvironmentFile=/etc/slurm-deck-web/agent.env`, `RuntimeDirectory=slurm-deck-web`, `RuntimeDirectoryPreserve=yes`, `Restart=always`, `RestartSec=2`, `ProtectSystem=true` (keeps `/usr` and `/boot` read-only; `/etc` stays writable for `useradd`/`groupadd`), `ProtectHome=read-only`, `NoNewPrivileges=yes` (dropping to a user needs no new privileges), `PrivateTmp=yes`, `LogsDirectory=slurm-deck-web`.

- [ ] **Step 1:** Tests (fake binaries record their argv to a log file):
  ```python
  def test_queue_hides_names_from_other_users(agent_as("amasha")):
      jobs = call("cluster.queue")["jobs"]; other = next(j for j in jobs if j["user"] == "hassan")
      assert "name" not in other
  def test_worker_cannot_call_account_verbs(agent_as_worker): ...        # 403
  def test_create_refuses_uid_outside_range(agent_as_admin): ...         # uid 1500, link_existing False → 409
  def test_create_link_existing_requires_matching_owner(agent_as_admin): # folder owner 2014, uid 2015 → 409
  def test_create_rolls_back_on_gpuhost_failure(agent_as_admin):         # fake ssh exits 1 on create-folders
      assert "userdel x" in fake_log() and "sacctmgr -i delete user x" in fake_log()
  def test_delete_refuses_non_webuser(agent_as_admin): ...               # shell user → 403, no commands logged
  def test_user_cannot_create_accounts(agent_as("amasha")): ...         # 403
  def test_agent_client_roundtrip(agent): ...                            # AgentClient.call("cluster.disk_free") returns ints
  ```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** `pytest -q` → PASS.
- [ ] **Step 5:** Commit `<KEY>: add cluster and account verbs, web AgentClient and systemd unit`.

---

## Phase exit check

- [ ] `pytest -q` and `sudo -E pytest -q -m root` green in CI.
- [ ] On a test VM (or the login node with a throwaway username): start deck-agent, call `cluster.status` through `AgentClient` as a fake worker uid, create and delete a throwaway account end to end, confirm both nodes show then lose it and `/shared/users/<name>` is archived.
