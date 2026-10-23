# Slurm Deck Web — Implementation Roadmap

> **For agentic workers:** this file is the index for seven phase plans. Read it
> first, then the phase plan you are executing. Each phase plan uses
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans, task by task.

**Spec:** `docs/specs/2026-10-23-web-platform-design.md` (approved 2026-10-23).
Every plan argues from it; read both.

**Goal:** replace the SSH TUI for normal users and admins with a browser-only
platform on the login node, keeping Slurm as the workload manager.

---

## Phases

| # | Plan | Delivers (working on its own) | Depends on |
|---|---|---|---|
| 1 | `2026-10-23-p1-core-and-agent.md` | Repo scaffold, CI, ported `sdcore`, **deck-agent** (protocol, session check, run-as-user, audit, cluster + account verbs), **GPU-host helper** | — |
| 2 | `2026-10-23-p2-web-foundation.md` | Postgres schema, sign-in/sessions/CSRF/lockout, set/reset password, mail outbox, accounts + applications + allow-list + reconnect + delete + View as user, React shell + sign-in + admin Users/Requests pages, Compose + Caddy | 1 |
| 3 | `2026-10-23-p3-jobs.md` | New job flow, submit/cancel/list/history/detail, live logs, extend + cap, templates, rerun, home dashboard + live updates, expiry warnings, notify-when-free, smoke test | 1, 2 |
| 4 | `2026-10-23-p4-files-and-uploads.md` | File manager, tus resumable uploads, downloads (file + folder zip), extract, free-space checks | 1, 2 |
| 5 | `2026-10-23-p5-interactive-sessions.md` | Notebook / TensorBoard / terminal job renderers, authenticated reverse proxy (HTTP + WebSocket), Services page | 1, 2, 3 |
| 6 | `2026-10-23-p6-envs-models-admin.md` | Environments (prebuilt, build-as-job, images), Models (HF download as job), Usage, admin Settings / Jobs / Usage / Cluster control / Shared assets / Monitoring | 1–5 |
| 7 | `2026-10-23-p7-hardening-and-cutover.md` | Installer, cluster hardening (docker group, shared dirs, sshd AllowGroups, service accounts, firewall, port forward, avahi, CA), backups, acceptance run, cutover + rollback tooling | 1–6 |

Phases 3 and 4 can run in parallel once 2 is merged. Each phase is one or more
SerenEdge tasks; each task in a plan is one `task/<KEY>-<slug>` branch and one
pull request into `dev`.

---

## Tech stack (decided 2026-10-23)

| Part | Stack |
|---|---|
| Frontend | React 18 + TypeScript + Vite; Tailwind CSS (spec §6 tokens as CSS variables); TanStack Query; tus-js-client; xterm.js. Tests: Vitest + @testing-library/react (dev only). |
| Backend (`sdweb`) | Python ≥ 3.11, FastAPI, Uvicorn, SQLAlchemy 2, Alembic, psycopg 3, argon2-cffi, httpx. Tests: pytest. |
| deck-agent | Python ≥ 3.11 stdlib (`http.server` over a Unix socket, `subprocess` with `user=`/`group=`/`extra_groups=`) + psycopg 3 (read-only). |
| GPU-host helper | Single-file Python stdlib script. |
| Infra | Docker Compose, Caddy 2, PostgreSQL 16, systemd. |

**Additions beyond the chosen stack that the owner must OK before Phase 2/6
starts (CLAUDE.md rule 5):** `cryptography` (Fernet, to encrypt HuggingFace
tokens at rest — spec §6.8). Nothing else is added without asking.

---

## Repository layout (all phases build into this)

```
.gitattributes                 * text=auto eol=lf   (Phase 1, Task 1)
pyproject.toml                 one project, packages under src/, extras [web] [agent] [dev]
src/
  sdcore/                      pure logic shared by web + agent (ported from legacy/v1.4-tui)
    launchspec.py  pods.py  sbatch.py  slurmparse.py  validate.py  connect.py
    extract.py  envspec.py  names.py
  deckagent/                   root service on the login node
    config.py  server.py  protocol.py  sessions.py  runas.py  audit.py
    grants.py  gpuhost.py  fsops.py  identity.py
    verbs/  __init__.py  cluster.py  jobs.py  files.py  accounts.py  admin.py
  sdweb/                       FastAPI app + worker (containers)
    config.py  db.py  models.py  security.py  agent.py  deps.py  audit.py
    mail/  auth/  accounts/  jobs/  files/  proxy/  envs/  modelslib/
    usage/  notify/  admin/  live/  worker/
    migrations/                Alembic
    app.py
gpuhost/
  sd-gpu-helper                forced-command script installed on the GPU host
frontend/                      Vite + React app (built into the web image)
deploy/
  compose.yaml  Caddyfile  web.Dockerfile
  systemd/  deck-agent.service  sd-stats-writer.service
  installer/                   Phase 7
  cluster/                     ported cluster-side files (resize-pods.sh, mailer,
                               stats writer, env specs, image defs)
tests/
  core/  agent/  web/  gpuhost/  e2e/
.github/workflows/ci.yml
```

---

## Global constraints (apply to every task in every phase)

- Work comes from SerenEdge. Branch `task/<KEY>-<short-slug>` (or
  `issue/<KEY>-<short-slug>`) off `dev`; PR into `dev`. Commit messages
  `<KEY>: short imperative summary`. In plan steps, `<KEY>` is the SerenEdge key
  of the task being built.
- Never add `Co-Authored-By`, "Generated with", or any AI/agent attribution to
  commits, PRs, code comments or docs.
- Never commit secrets or `.env` files. Site config is `site.env` (gitignored);
  ship `*.example` templates.
- No new frameworks or dependencies beyond the tech stack table above without
  asking.
- Nothing site-specific hardcoded: IPs, hostnames, ports, domains, timezone,
  node names come from config or the admin panel.
- Python ≥ 3.11; PostgreSQL 16; Node 20 LTS for the frontend build.
- Shell scripts and Python files use LF line endings.
- No passwords in email, ever (spec §5.3).
- All user-controlled values are HTML-escaped in every email and page (spec §8).
- The `web`/`worker` containers never run as root, never mount `/shared`, the
  munge key, `/etc/shadow` or the Docker socket (spec §4.1, §9.1).
- deck-agent never acts as root, a system account, a sysadmin, slurmadmin, or a
  shell user other than an attached account acting as itself (spec §4.3).

---

## Shared names (fixed here so every phase uses the same ones)

### Linux accounts and groups
| Name | Where | Purpose |
|---|---|---|
| `sdweb` | login node | runs `caddy`, `web`, `db` containers; may connect to deck-agent |
| `sdworker` | login node | runs `worker` container; read-only cluster verbs only |
| `sd-ops` | login node + GPU host, same UID | member of `gpuadmins`; identity for admin file verbs |
| `sdprov` | GPU host | SSH login for the GPU-host helper (forced command + sudo for that one script) |
| `webusers` | both nodes | every hidden web-user account; denied by sshd |
| `gpuusers`, `gpuadmins` | both nodes | existing groups, unchanged meaning |

### Paths and files
| Name | Default |
|---|---|
| Install dir | `/opt/slurm-deck-web` (owned by slurmadmin) |
| Agent socket | `/run/slurm-deck-web/agent.sock` |
| Agent config | `/etc/slurm-deck-web/agent.env` (root 0600) |
| Agent local audit log | `/var/log/slurm-deck-web/agent-audit.jsonl` (root 0600) |
| Web config | `/etc/slurm-deck-web/web.env` (slurmadmin:sdweb 0640) |
| Secrets | `/etc/slurm-deck-web/secrets.env` (slurmadmin:sdweb 0640) |
| GPU helper | `/usr/local/sbin/sd-gpu-helper` on the GPU host |
| Stats file | `$NFS_ROOT/.gpu_stats.json` (existing writer) |
| Backups | `/var/backups/slurm-deck/` |

### Fixed values from the spec
| Value | Setting | Default |
|---|---|---|
| Session sliding expiry | `SESSION_IDLE_MINUTES` | 30 |
| Session absolute cap | `SESSION_MAX_HOURS` | 12 |
| Password minimum length | `PASSWORD_MIN_LEN` | 12 |
| Lockout | `LOCKOUT_FAILS` / `LOCKOUT_WINDOW_MIN` / `LOCKOUT_MIN` | 10 / 15 / 15 |
| Set-password link life | `SET_LINK_HOURS` | 24 |
| Reset link life | `RESET_LINK_HOURS` | 1 |
| Default job time | admin setting `default_time_limit` | `08:00:00` |
| Extension cap (total hours per job) | admin setting `extension_cap_hours` | 24 (never above partition MaxTime) **[plan's call]** |
| Extension choices | — | +1 h, +2 h, +4 h |
| Expiry warning | `EXPIRY_WARN_MINUTES` | 30 |
| Job submit rate limit | admin setting `submit_rate_per_hour` | 20 **[plan's call — legacy `JOB_RATE_LIMIT`]** |
| Disk alert | admin setting `disk_alert_percent` | 90 |
| Upload chunk size | `UPLOAD_CHUNK_MB` | 64 **[plan's call within spec's 64–100]** |
| Upload resume window | `UPLOAD_RESUME_HOURS` | 24 |
| Interactive session ports | `SESSION_PORT_RANGE` | `8800-8999` **[plan's call]** |
| Backups kept | `BACKUP_KEEP` | 14 |

### deck-agent protocol (Phase 1 defines; every later phase calls it)
- HTTP/1.1 over the Unix socket. `POST /v1/<verb>`, e.g. `POST /v1/job.submit`.
- Request headers: `X-SD-Session: <raw session token>` (user verbs),
  `X-SD-Grant: <upload grant>` (upload chunks). There is no act-as header:
  View as user is a column on the admin's session row (`acting_as_username`),
  which deck-agent reads itself, so `web` cannot forge it.
- JSON body for ordinary verbs; raw bytes body for `fs.write_chunk`
  (`X-SD-Offset`, `X-SD-Upload` headers carry the rest).
- Response: `200` + JSON `{"ok": true, "data": ...}`; errors
  `{"ok": false, "error": {"code": "<slug>", "message": "<plain words>"}}` with
  status 400 (bad input), 401 (no/invalid session), 403 (not allowed),
  404, 409 (conflict), 422 (validation), 500. Streaming verbs
  (`fs.download_stream`, `fs.read`, `joblog.tail`) return raw bytes with
  `Content-Type` set.
- `sdweb.agent.AgentClient` (Phase 1, Task 9) is the only caller.
