# Phase 5 — Interactive Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JupyterLab, TensorBoard and terminal sessions run as Slurm jobs and open in a new browser tab at `https://<host>/notebook/<job_id>/`, `/tensorboard/<job_id>/` or the platform terminal page `/sessions/terminal/<job_id>`, with no token or tunnel, reachable only by the job's owner (and admins).

**Architecture:** The job script starts the service on the GPU node bound to its NodeAddr on a free port in `SESSION_PORT_RANGE`, with a per-job random token, and prints one machine-readable `SD_SESSION` line. `web` asks deck-agent for that line (read as the owner), checks ownership on every request and WebSocket upgrade, and reverse-proxies with the token added server-side and the user's platform cookie stripped. Terminals use Jupyter Server's terminal API (no extra binary); TensorBoard sits behind a tiny token guard because it has no auth of its own.

**Tech Stack:** as Phase 2; `websockets` (already installed by `uvicorn[standard]`; declare it explicitly in `[web]`); xterm.js in the frontend.

**Spec:** §6.4, §6.9, §10.5, §13 scenarios 1 and 6. **Roadmap:** `SESSION_PORT_RANGE` 8800–8999.

## Global Constraints

- Roadmap constraints apply.
- JupyterLab always launches from the shared env `SD_JUPYTER_ENV` (default `/shared/envs/data-science`); the user's chosen env becomes the default kernel when it has `ipykernel`, otherwise the job prints `SD_WARN kernel-fallback` and the data-science kernel is used. Never `pip install --user jupyterlab`.
- Jupyter flags: `--ServerApp.base_url=/notebook/$SLURM_JOB_ID/`, `--ServerApp.allow_origin=https://<SD_PUBLIC_HOSTNAME>`, `--IdentityProvider.token=$SD_TOKEN`, `--FileContentsManager.delete_to_trash=False`, `--ServerApp.websocket_ping_interval=30`, `--ServerApp.websocket_ping_timeout=30` (exact names verified against the installed jupyter_server with `jupyter server --help-all` in Task 1), `--no-browser`, `--ServerApp.root_dir=/shared/users/$USER`, `--port-retries=0`.
- The proxy never forwards the `sd_session` cookie or `X-CSRF-Token` to the job.
- Copy: starting page "Starting your session…"; ended page "This session has ended." with "Back to your jobs"; refused "This session belongs to someone else." (403).

## Review Focus

- **Job still RUNNING but the server inside crashed** — proxy shows "The session isn't responding. It may still be starting, or it has stopped." with a link to the job's log, not a raw 502. Test in Task 4.
- **Admin opens a user's notebook** — allowed and audited as `session_open` with `acting_admin`; a normal user pasting the URL gets 403. Test in Task 4.
- **WebSocket dropped by the browser** — upstream socket closed too; no leaked connections after 100 open/close cycles. Test in Task 4.
- **Port already taken on the node** — the job picks another port in range; the `SD_SESSION` line always names the port actually bound. Test in Task 1.
- **Jupyter redirects to `/login` or absolute URLs** — rewritten so they stay under `/notebook/<id>/`. Test in Task 4.

---

### Task 1: Session job renderers

**SerenEdge:** `SLURM-32`

**Files:**
- Modify: `src/sdcore/sbatch.py`, `tests/core/test_sbatch.py`
- Create: `src/sdcore/tbguard.py`, `tests/core/test_tbguard.py`
- Source: `legacy/v1.4-tui:slurmdeck/jobs.py` (`render_notebook_sbatch`, `render_tensorboard_sbatch`, `_NODE_ADDR_SNIPPET`, `_free_port_snippet`, `_user_home_snippet`, `_ready_marker_snippet`).

**Interfaces:**
- Produces:
  - `SessionOptions(public_origin: str, jupyter_env: str, port_lo: int, port_hi: int)`.
  - `render_notebook(spec: JobSpec, folder: str, home: str, env: EnvChoice, opts: SessionOptions, mail_types: str) -> str`
  - `render_terminal(spec, folder, home, env, opts, mail_types) -> str` — Jupyter Server only (`jupyter server`, same flags, `base_url=/terminal/$SLURM_JOB_ID/`), `SHELL=/bin/bash`, terminals enabled, contents manager root `/shared/users/$USER`.
  - `render_tensorboard(spec, folder, home, env, logdir: str, opts, mail_types) -> str` — TensorBoard on `127.0.0.1:<inner port>` with `--path_prefix=/tensorboard/$SLURM_JOB_ID`, fronted by `python -m sdcore.tbguard --listen $SD_NODE_ADDR:$SD_PORT --upstream 127.0.0.1:<inner> --token $SD_TOKEN` (the guard file is copied into the job folder by deck-agent at submit, so no import path is needed on the node; see Task 2).
  - All three: `$SD_TOKEN` from `python3 -c 'import secrets;print(secrets.token_hex(24))'`; free port scan over `opts.port_lo..port_hi` starting at `port_lo + SLURM_JOB_ID % (span)`; then print exactly one line `SD_SESSION kind=<notebook|terminal|tensorboard> node=<addr> port=<port> token=<token>` **after** the port is bound by the service (the ready-marker loop prints it when `/dev/tcp/<addr>/<port>` connects) and touch `.sd-ready`.
  - `sdcore.connect.parse_session_line(out_text: str) -> SessionInfo | None` with `SessionInfo(kind, node, port, token)` (last matching line wins).
  - `tbguard`: stdlib `http.server` + `http.client` forwarder; 401 unless header `X-SD-Token` equals the token (`hmac.compare_digest`); streams bodies.

- [ ] **Step 1:** Tests:
  ```python
  def test_notebook_flags(): s = render_notebook(...)
      for flag in ["--FileContentsManager.delete_to_trash=False", "--ServerApp.websocket_ping_interval=30",
                   "--ServerApp.base_url=/notebook/$SLURM_JOB_ID/", "--ServerApp.allow_origin=https://slurmdeck.local"]:
          assert flag in s
      assert "pip install --user jupyterlab" not in s and "/shared/envs/data-science" in s
  def test_session_line_printed_after_bind(): ...     # order: service start before the marker loop that echoes SD_SESSION
  def test_parse_session_line_last_wins(): ...
  def test_port_scan_stays_in_range(): ...            # run the snippet with a fake SLURM_JOB_ID and ports 8800-8801 occupied
  def test_tbguard_rejects_missing_token(tb_upstream): ...
  def test_scripts_pass_bash_n(): ...
  ```
  Also a one-off verification step: on a node with the data-science env, run `jupyter server --help-all | grep -E "delete_to_trash|websocket_ping_(interval|timeout)|allow_origin|base_url"` and record the output in the PR; adjust flag names if they differ.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add notebook, terminal and TensorBoard session renderers`.

---

### Task 2: deck-agent session verb and submit support

**SerenEdge:** `SLURM-33`

**Files:**
- Modify: `src/deckagent/verbs/jobs.py` (`job.submit` accepts `extra_files: {"tbguard.py": <sdcore.tbguard source>}` limited to that one allowed name, written next to `job.sbatch`), `tests/agent/test_verbs_jobs.py`
- Create: `tests/agent/test_session_info.py`

**Interfaces:**
- Produces: `session.info {job_id}` (user/admin) → `{"state", "ready": bool, "kind", "node", "port", "token"}`; reads the job's `.out` as the owner (admin via `sd-ops`) and `parse_session_line`; `ready` = `.sd-ready` exists and state RUNNING. Non-owner non-admin → 404. Only `kind/node/port/token` from the owner's own output are returned; node must equal the job's allocated node from `scontrol` (prevents a user's script from pointing the proxy at another host) and port must be inside `SESSION_PORT_RANGE`.

- [ ] **Step 1:** Tests: a `.out` claiming `node=10.0.0.5` while the job ran on the compute node → `ready: false`, error `session_mismatch`; port 22 → refused; other user → 404; admin → ok and audited.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add session.info verb with node and port checks`.

---

### Task 3: Interactive intents in the jobs service

**SerenEdge:** `SLURM-34`

**Files:**
- Modify: `src/sdweb/jobs/service.py`, `src/sdweb/jobs/routes.py`, `tests/web/test_jobs_api.py`

**Interfaces:**
- Consumes: Task 1 renderers; Phase 3 `build_script`.
- Produces: `build_script` handles intents `notebook`, `terminal` (refused 403 `terminal_disabled` when setting `terminal_jobs_enabled` is false), `tensorboard` (`logdir` must be inside the user's browse roots). `GET /api/jobs/{id}` adds `session: {kind, ready, open_url}` for session jobs, `open_url`: notebook `/notebook/<id>/lab`, tensorboard `/tensorboard/<id>/`, terminal `/sessions/terminal/<id>` (the platform's own xterm.js page, which talks to the proxied Jupyter Server at `/terminal/<id>/`).

- [ ] **Step 1:** Tests: terminal intent refused when disabled; tensorboard logdir outside jail → 422; notebook job detail returns `open_url` ending `/lab` once ready.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add notebook, terminal and TensorBoard job intents`.

---

### Task 4: Authenticated reverse proxy

**SerenEdge:** `SLURM-35`

**Files:**
- Create: `src/sdweb/proxy/__init__.py`, `src/sdweb/proxy/routes.py`, `src/sdweb/proxy/targets.py`, `src/sdweb/proxy/pages.py`, `tests/web/test_proxy.py`

**Interfaces:**
- Consumes: Task 2 `session.info`.
- Produces:
  - `targets.resolve(ctx: SessionCtx, kind: str, job_id: str) -> Target | ProxyPage` with a 15 s cache per `(account, job_id)`; `Target(base: str, auth_headers: dict)` — notebook/terminal: `{"Authorization": "token <t>"}`; tensorboard: `{"X-SD-Token": "<t>"}`.
  - Routes `/{kind}/{job_id}/{path:path}` for `kind ∈ {notebook, terminal, tensorboard}`, all HTTP methods: session required (no CSRF — Jupyter's own XSRF/token handles the app; our cookie is `SameSite=Strict`), forwards to `http://<node>:<port>/<kind>/<job_id>/<path>?<query>` with `httpx.AsyncClient` streaming both ways, no timeout on body streaming, 10 s connect timeout. Request headers dropped: `Cookie` entries named `sd_session`, `X-CSRF-Token`, `Host` (set to upstream), hop-by-hop headers. Response `Location` headers pointing at the upstream origin are rewritten to the public origin.
  - WebSocket route on the same paths: ownership checked at upgrade; upstream via `websockets.connect` with the auth header and `Origin: https://<SD_PUBLIC_HOSTNAME>`; bidirectional pump; either side closing closes both.
  - `pages.starting()`, `pages.ended()`, `pages.not_responding(job_id)`, `pages.forbidden()` — small HTML using the spec §6 tokens, auto-refresh every 3 s on `starting`.
  - Audit `session_open` once per `(account, job_id)` per hour.

- [ ] **Step 1:** Tests with a fake upstream (a small uvicorn app started by the test, serving `/notebook/42/...` and a WebSocket echo):
  ```python
  def test_owner_proxied_with_token_and_without_our_cookie(client_owner, upstream):
      client_owner.get("/notebook/42/api/status"); h = upstream.last_headers
      assert h["authorization"] == "token T" and "sd_session" not in h.get("cookie", "")
  def test_other_user_403(client_other): ...
  def test_admin_allowed_and_audited(client_admin): ...
  def test_not_ready_shows_starting_page(client_owner, agent_not_ready): ...
  def test_ended_job_shows_ended_page(...): ...
  def test_upstream_down_shows_not_responding(...): ...
  def test_location_rewritten(...): ...
  def test_websocket_roundtrip_and_no_leak(client_owner, upstream_ws):  # 100 open/close, upstream open count returns to 0
  ```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add authenticated reverse proxy for interactive sessions`.

---

### Task 5: Frontend — Open, terminal tab, Services page

**SerenEdge:** `SLURM-36`

**Files:**
- Create: `frontend/src/pages/Terminal.tsx` (route `/sessions/terminal/:jobId`; connects to `/terminal/<id>/terminals/websocket/<name>` through the proxy), `frontend/src/api/sessions.ts`, `frontend/src/pages/Services.tsx`, `frontend/src/components/StartTensorBoard.tsx`, tests alongside.
- Modify: `frontend/src/components/JobCard.tsx`, `frontend/src/pages/JobDetail.tsx` (Open button → `window.open(open_url, "_blank", "noopener")`; disabled with "Starting…" until `ready`).

**Interfaces:**
- Produces:
  - Terminal page: `POST /terminal/<id>/api/terminals` (through the proxy) to create a terminal, then xterm.js over the terminado protocol (`["stdin", data]`, `["stdout", data]`, `["set_size", rows, cols, ...]`), fit-to-window, reconnect button.
  - Services page: my running notebooks, TensorBoards, terminals (from `/api/jobs` filtered by kind) with Open / Stop (cancel), and "Start TensorBoard" (pick a log dir with `FilePicker` in dir mode).

- [ ] **Step 1:** Vitest: Open disabled until ready; terminal sends `set_size` on resize; Services lists only session kinds.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add session open buttons, browser terminal and Services page`.

---

## Phase exit check

- [ ] On the test VM: start a notebook as a hidden web user, open it in a new tab, run a cell, delete a file in Jupyter (no `.Trash` error), open a terminal session and run `nvidia-smi`, start TensorBoard on a run folder; a second user pasting each URL gets 403. (The GPU-host firewall limiting the port range to the login node lands in Phase 7 Task 3.)
