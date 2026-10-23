# Phase 6 — Environments, Models, Usage and Admin Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything else the TUI did: prebuilt and personal environments (built as Slurm jobs), container images, HuggingFace model downloads (as Slurm jobs), personal and cluster usage, and the remaining admin sections — Settings, Jobs, Usage, Cluster control, Shared assets, Monitoring.

**Architecture:** Long-running work (env builds, prebuilt installs, model downloads) is rendered by `sdcore` and submitted through the Phase 3 `job.submit` path, so it runs on the GPU host under Slurm with logs streamed by the existing log viewer. Admin cluster operations are new deck-agent verbs that run as root (Slurm control) or `sd-ops` (shared files), each audited.

**Tech Stack:** as Phase 2, plus `cryptography` (Fernet) for HF tokens — **only after the owner OKs it** (roadmap). If not approved, store no HF tokens and ask for the token per download (kept only for that job).

**Spec:** §6.7, §6.8, §6.11, §7, §8 (disk-full), §10.3–10.4, §13 scenarios 7, 8, 12. **Roadmap:** shared names (`sd-ops`).

## Global Constraints

- Roadmap constraints apply.
- `/shared/envs`, `/shared/models`, `/shared/datasets`, `/shared/data`, `/shared/images`, `/shared/scripts` are written only by `sd-ops` (admin actions). Users' own envs live in `/shared/users/<u>/envs/<name>`, own models in `/shared/users/<u>/models/<name>`.
- Prebuilt env specs carry an upper bound on every fast-moving library at the major version verified on the cluster (record the verified versions in the PR); at minimum `transformers` and `trl`.
- Env builds verify the resulting package set (legacy `_verify_spec_packages`); an env that fails verification is not listed as usable.
- Model downloads set `HF_HUB_DISABLE_XET=1` and `max_workers=4`; the HF token never appears in a job script, the job environment listing, or a log line.
- Disk alert: email all active admins once per 24 h while `/shared` used ≥ `disk_alert_percent`.
- QoS edits must preserve other `MaxTRESPerUser` entries (the legacy clobber bug, `legacy/v1.4-tui` commit `212cc6e`).

## Review Focus

- **Env build job killed by the time limit or OOM** — the env is marked failed with the explanation from Phase 3, not shown as ready. Test in Task 2.
- **Gated HF repo with a wrong token** — job fails with "HuggingFace refused the token for this repository.", and the token file is still deleted. Test in Task 3.
- **Admin resizes pods while jobs are queued** — refused with the script's own reason (it requires an empty queue); nothing half-applied. Test in Task 5.
- **Publishing a user's dataset whose name already exists in the shared area** — refused unless Replace is chosen. Test in Task 5.
- **Audit log with 100 000 events** — the admin page pages and filters server-side within 1 s. Test in Task 6.

---

### Task 1: Ported env specs, image defs and `sdcore.envspec`

**Files:**
- Create: `deploy/cluster/envs/*.yml`, `deploy/cluster/images/*.def`, `src/sdcore/envspec.py`, `tests/core/test_envspec.py`
- Source: `legacy/v1.4-tui:envs/specs/*.yml`, `deploy/images/*.def`, `slurmdeck/setup.py` (`_parse_spec_pip_deps`, `_verify_spec_packages`), `slurmdeck/envbuilder.py` (`_smoke_check_pytorch`), `tests/test_prebuilt_envs.py`.

**Interfaces:**
- Produces: `list_specs(spec_dir: str) -> list[EnvSpecInfo(name, description, path)]`; `parse_pip_deps(spec_text: str) -> list[str]`; `top_level_names(deps: list[str]) -> list[str]`; `VERIFY_SNIPPET: str` (shell that prints `SD_ENV_MISSING <pkg>` lines and `SD_ENV_OK` when none); `render_env_build(user, folder, home, *, kind: "conda"|"venv", name: str, dest: str, packages: str, requirements_path: str | None, spec_path: str | None) -> str` (CPU-only job: 0 pods, 8 CPU, 16 GB, `04:00:00`; `TMPDIR`/`PIP_CACHE_DIR` under the dest's parent, not `/tmp`); `parse_env_result(out_text) -> tuple[bool, list[str]]`.

- [ ] **Step 1:** Port legacy prebuilt-env tests; add: every spec bounds `transformers` and `trl` (`<` present); `render_env_build` contains no `pip install --user`; `parse_env_result` returns `(False, ["torch"])` for one `SD_ENV_MISSING torch` line.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: port env specs and image defs with version bounds and build renderer`.

---

### Task 2: Environments — agent verbs, API, page

**Files:**
- Create: `src/deckagent/verbs/envs.py`, `src/sdweb/envs/__init__.py`, `src/sdweb/envs/routes.py`, `src/sdweb/migrations/versions/0006_envs.py`, `frontend/src/pages/Environments.tsx`, `frontend/src/api/envs.ts`, tests: `tests/agent/test_verbs_envs.py`, `tests/web/test_envs_api.py`, `frontend/src/pages/Environments.test.tsx`
- Modify: `src/sdweb/jobs/service.py` (`preview` fills `warnings` with missing packages), `frontend/src/pages/NewJob/StepInputs.tsx` (environment dropdown from `/api/envs`)

**Interfaces:**
- Produces:
  - Agent verbs: `env.list` → `{"prebuilt": [...], "mine": [...], "images": [...]}` each `{name, path, kind, ready}` (`ready` = `.sd-env-ok` marker present); `env.check_imports {env_path, script_path}` → `{"missing": [str]}` (parses top-level `import`/`from` names from the script with `ast`, then runs the env's python `-c` with `importlib.util.find_spec` as the user on the login node, 20 s timeout; stdlib names ignored); `env.delete {path}` (own envs only; admin `as_admin` for shared, via `sd-ops`).
  - Build/install submit through Phase 3 `job.submit` with `kind` `env_build` or `env_install_prebuilt` (admin only; submitted **as `sd-ops`** — deck-agent `job.submit` gains `as_ops: true` for admin callers; `sd-ops` gets a Slurm association in Phase 7). The worker can't read job logs (it has no user identity), so `web` finalizes results lazily on `GET /api/envs`: for env jobs in `jobs` with `last_state` terminal and no result recorded, `web` calls `joblog.read` with the requesting user's session, stores the result in `env_builds(job_id pk, account_id, path, ok bool, missing jsonb, finished_at)`, and writes `.sd-env-ok` via agent `fs.write` when ok.
  - API: `GET /api/envs`, `POST /api/envs/build {kind, name, packages?, requirements_path?}`, `DELETE /api/envs?path=`, admin `POST /api/admin/envs/install {spec}`.
  - Page: three tables (Prebuilt, My environments, Container images), Build environment dialog, build progress linking to the job's log.

- [ ] **Step 1:** Tests: `check_imports` reports `tensorboard` missing for a script importing it (fake env python); a failed build (`SD_ENV_MISSING torch`) is listed `ready:false` with the missing list; non-admin prebuilt install → 403; `preview` warnings contain "Python package 'tensorboard' isn't in the chosen environment."
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add environments listing, builds as jobs and missing-package warnings`.

---

### Task 3: Models — HF downloads as jobs, token storage, page

**Files:**
- Create: `src/sdcore/hfdownload.py`, `src/sdweb/modelslib/__init__.py`, `src/sdweb/modelslib/routes.py`, `src/sdweb/modelslib/tokens.py`, `src/sdweb/migrations/versions/0007_models.py`, `frontend/src/pages/Models.tsx`, tests: `tests/core/test_hfdownload.py`, `tests/web/test_models_api.py`
- Modify: `src/deckagent/verbs/jobs.py` (`job.submit` accepts `secret_file: {"name": ".hf_token", "content": str}` written mode 0600 as the user beside `job.sbatch`; only that name allowed)

**Interfaces:**
- Produces:
  - `render_hf_download(user, folder, home, *, repo_id: str, dest: str, revision: str | None) -> str` — CPU job (0 pods, 4 CPU, 8 GB, `08:00:00`); reads `.hf_token` into `HF_TOKEN` if present, deletes the file immediately, `set +x` around it; uses the data-science env's `huggingface_hub.snapshot_download(repo_id, local_dir=dest, max_workers=4)`; prints `SD_HF_DONE <bytes>` or `SD_HF_FAIL <reason>` where 401/403 → `auth`.
  - `repo_id` rule: `^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$`.
  - `tokens.save(db, account, token)` / `tokens.load(db, account) -> str | None` with Fernet key `SD_FERNET_KEY` from `secrets.env`; table `hf_tokens(account_id pk, ciphertext, updated_at)`.
  - API: `GET /api/models` (shared + mine, via `fs.list`), `POST /api/models/download {repo_id, revision?, use_saved_token, token?, save_token}`, `PUT/DELETE /api/models/token`, admin `POST /api/admin/models/publish` (Task 5's publish verb).
  - Page: library table (name, size, owner/shared), Download dialog with progress via the job log, token field (masked, "Save for next time").

- [ ] **Step 1:** Tests: the rendered script never contains the token text; `.hf_token` handled with `rm -f` before the download starts; `SD_HF_FAIL auth` maps to "HuggingFace refused the token for this repository."; invalid `repo_id` → 422; saved token round-trips encrypted (ciphertext ≠ plaintext).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add model library and HuggingFace downloads as Slurm jobs`.

---

### Task 4: Usage — personal and cluster

**Files:**
- Create: `src/deckagent/verbs/usage.py`, `src/sdcore/usage.py`, `src/sdweb/usage/__init__.py`, `src/sdweb/usage/routes.py`, `frontend/src/pages/Usage.tsx`, `frontend/src/pages/admin/UsageAdmin.tsx`, tests: `tests/core/test_usage.py`, `tests/agent/test_verbs_usage.py`
- Source: `legacy/v1.4-tui:slurmdeck/accounting.py`.

**Interfaces:**
- Produces:
  - `sdcore.usage.summarize(rows: list[SacctRow], days: int) -> UsageSummary(gpu_hours: float, cpu_hours: float, jobs_by_state: dict[str, int])` where GPU-hours = `gres/shard` count / pods_total × elapsed hours (one pod = 1/pods_total GPU).
  - Agent: `usage.personal {days ∈ 7|30|90}` (as the user), `usage.cluster {days}` (admin, `-a`, grouped by user), `admin.disk_usage` (admin; `du -sb` per user over **both** `users/<u>` and `jobs/<u>` via `sd-ops`; 10 min cache in deck-agent).
  - API: `GET /api/usage?days=30`, admin `GET /api/admin/usage?days=30`, `GET /api/admin/disk-usage`.
  - Pages: personal (three numbers + jobs-by-state bar), admin (per-user table sortable, disk usage by user).
  - **Hardware stats** page (`/usage/hardware`: GPU util, VRAM, temperature, power, CPU, RAM from `cluster.status`, live) and **Cluster status** page (`/usage/cluster`: node state, partition, pods, running/pending counts, `admin.service_status`-free health summary for users: "Scheduler reachable", "GPU node up", "Stats fresh") — the TUI's "Hardware stats" and "Cluster status" (spec §6.11).

- [ ] **Step 1:** Tests: Cluster status shows "Stats fresh" false when `live_stats` is false; 2 pods × 3 h on a 4-pod node = 1.5 GPU-hours; disk usage counts both trees; non-admin cluster usage → 403.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add personal and cluster usage and per-user disk usage`.

---

### Task 5: Admin cluster control and shared assets

**Files:**
- Create: `src/deckagent/verbs/admin.py`, `deploy/cluster/resize-pods.sh`, `src/sdweb/admin/__init__.py`, `src/sdweb/admin/routes.py`, `frontend/src/pages/admin/Cluster.tsx`, `frontend/src/pages/admin/SharedAssets.tsx`, `frontend/src/pages/admin/JobsAdmin.tsx`, tests: `tests/agent/test_verbs_admin.py`, `tests/web/test_admin_api.py`
- Source: `legacy/v1.4-tui:slurmdeck/admin.py` (`list_qos`, `set_qos_*`, `drain_node`, `resume_node`, `cancel_jobs_on_node`, pod grid), `deploy/resize-pods.sh` and `tests/test_resize_pods_script.py`.

**Interfaces:**
- Produces (agent verbs, admin only, run as root unless noted):
  - `admin.qos_list` → `[{name, max_wall_s, max_pods_per_user, max_gpus_per_user, priority}]`; `admin.qos_set {name, field ∈ max_wall|max_pods_per_user|max_gpus_per_user|priority, value | null}` — reads current `MaxTRESPerUser`, changes only the one TRES key, writes back.
  - `admin.drain {node, reason (required, ≤ 200 chars), cancel_running: bool}`, `admin.resume {node}`, `admin.node_jobs {node}`.
  - `admin.pods` → occupancy grid `[{pod: i, job_id|null, user|null}]` and `fits_new_pod_count` previews for 1..8; `admin.pods_resize {n}` → runs `runuser -u slurmadmin -- <install>/deploy/cluster/resize-pods.sh <n>`; passes its exit code and last 40 output lines through.
  - `admin.publish_shared {src, area ∈ datasets|models|envs|data|images|scripts, name, replace: bool}` → copy (as `sd-ops`, `cp -a --reflink=auto`) from a user area into `/shared/<area>/<name>`; refuses existing names unless `replace`; `admin.unpublish_shared {area, name}`.
  - `admin.service_status` → `{unit: active|inactive|failed}` for `slurmctld`, `slurmdbd`, `mariadb`, `munge`, `deck-agent`, `docker` on the login node, and `slurmd`, `munge`, `sd-stats-writer` on the GPU host (via a new helper op `service-status` added to `sd-gpu-helper`, allow-listed units only).
  - Web API mirroring each verb under `/api/admin/...`; admin Jobs page reuses Phase 3 components with all-users queue/history, cancel/extend any job, and log reading via `?user=`.
  - `resize-pods.sh` ported unchanged except: site values from `/etc/slurm-deck-web/site.env`; no hardcoded node name or SSH target.

- [ ] **Step 1:** Tests: QoS edit of `max_pods_per_user` keeps `gres/gpu=10` in the written `MaxTRESPerUser` (legacy test `test_set_qos_max_pods_per_user_none_clears_only_shard` ported); drain without reason → 422; resize refusal output passed through; publish onto an existing name without replace → 409; port the legacy `test_resize_pods_script.py` suite against the new path.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add admin cluster control, pods, shared assets and service health`.

---

### Task 6: Admin settings and monitoring, disk alerts

**Files:**
- Create: `src/sdweb/admin/settings_routes.py`, `src/sdweb/admin/monitoring_routes.py`, `src/sdweb/worker/disk_task.py`, `frontend/src/pages/admin/Settings.tsx`, `frontend/src/pages/admin/Monitoring.tsx`, tests: `tests/web/test_admin_settings.py`, `tests/web/test_monitoring.py`, `tests/web/test_disk_alert.py`
- Modify: `src/deckagent/verbs/admin.py` (add `admin.audit_tail {since_ts, limit ≤ 500}` reading the agent's JSONL log)

**Interfaces:**
- Produces:
  - `GET/PUT /api/admin/settings` for keys: `default_time_limit` (`HH:MM:SS`, ≤ partition max), `extension_cap_hours` (1..partition max hours), `submit_rate_per_hour` (0 = off), `mail_enabled`, `maintenance_banner` (≤ 500 chars, null clears), `terminal_jobs_enabled`, `disk_alert_percent` (50..99), `cluster_location`. Every change audited with old/new values.
  - Monitoring: `GET /api/admin/audit?actor=&action=&from=&to=&page=&page_size≤200` (server-side filtering on indexed `ts`, `actor_id`, `action`; merged view shows `source`), `GET /api/admin/agent-audit` (from `admin.audit_tail`), `GET /api/admin/mail-log?status=` (from `outbox`), `GET /api/admin/services` (from `admin.service_status` plus Compose container health read by `web` from its own healthcheck endpoint).
  - `disk_task.run_once` every 10 min (worker, `cluster.disk_free`): used ≥ threshold and no alert sent in 24 h (setting `last_disk_alert_at`) → `enqueue("disk_alert")` to all active admins.
  - Pages: Settings form with inline validation; Monitoring tabs (Audit, deck-agent log, Mail log, Services).

- [ ] **Step 1:** Tests: `extension_cap_hours` above partition max → 422; audit query over 100 000 seeded rows returns page 1 in < 1 s; disk alert sends once in 24 h; maintenance banner appears in the next live `cluster` message.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add admin settings, monitoring and disk-full alerts`.

---

## Phase exit check

- [ ] On the test VM: build a venv with `requirements.txt`, see it verified and usable in New job; download a small public HF model; check personal usage; as admin edit QoS, drain/resume, view pods, publish a dataset, see every action in the audit log.
