# Phase 2 — Web Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running web platform where an admin can create accounts, people can apply for access, everyone signs in with email + password, and the React shell, admin Users/Requests/Application-access pages, mail and Docker Compose deployment all work.

**Architecture:** FastAPI app `sdweb` with SQLAlchemy 2 models on PostgreSQL 16 and Alembic migrations; cookie sessions stored hashed; every privileged action goes through `AgentClient` (Phase 1). A separate `worker` process (same image) drains the mail outbox. React + Vite frontend served as static files by the same image behind Caddy.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, psycopg 3, argon2-cffi, httpx; React 18, TypeScript, Vite, Tailwind, TanStack Query, React Router; Vitest + Testing Library; Caddy 2; Docker Compose.

**Spec:** `docs/specs/2026-10-23-web-platform-design.md` §5 (all), §6 visual identity, §7 Requests/Users/Application access, §8, §9. **Roadmap:** `docs/plans/2026-10-23-web-platform-roadmap.md`.

## Global Constraints

- Roadmap constraints and shared names apply.
- Session cookie name `sd_session`; flags `HttpOnly; Secure; SameSite=Strict; Path=/`. CSRF header `X-CSRF-Token` must equal the session's `csrf_token` on every non-GET request.
- Sliding expiry 30 min, absolute 12 h, refreshed on each authenticated request (spec §5.3).
- Password min 12 chars, argon2id, refused if in `src/sdweb/auth/common-passwords.txt` (top 10 000 list, committed).
- Lockout: 10 failures in 15 min → locked 15 min, owner emailed. Per-IP: 30 attempts / 15 min.
- Set link 24 h, reset link 1 h, single use, stored hashed.
- No password ever in an email. Every email value HTML-escaped.
- Allow-list: empty ⇒ Apply form off and hidden. Domain match case-insensitive on the part after `@`, exact (case-insensitive) for single addresses, no subdomain matching.
- Apply form refusal copy, exactly: "Applications from this email aren't open — contact the cluster admin."
- Apply success copy, exactly: "Application received — you'll get an email once an admin reviews it."
- UIDs for new accounts come from Postgres sequence `web_uid_seq` (start `SD_WEB_UID_MIN` 20000, max 59999, no cycle).

## Review Focus

- **Two admins approving the same application at once** — exactly one account must result; the second gets 409. Test in Task 6.
- **Email case and whitespace** (`" Amasha@IIT.ac.lk "`) — sign-in, uniqueness and allow-list must treat it as `amasha@iit.ac.lk`. Tests in Tasks 3 and 6.
- **A reset link used twice, or after the password was changed another way** — second use refused. Test in Task 3.
- **Agent down during account creation** — no half-created DB account left that blocks retrying with the same email/username. Test in Task 5.
- **Admin disables themselves or deletes the last admin** — refused with a plain message. Test in Task 5.

---

### Task 1: Settings, database models, first migration, agent views

**SerenEdge:** `SLURM-11`

**Files:**
- Create: `src/sdweb/config.py`, `src/sdweb/db.py`, `src/sdweb/models.py`, `alembic.ini`, `src/sdweb/migrations/env.py`, `src/sdweb/migrations/versions/0001_initial.py`, `tests/web/conftest.py`, `tests/web/test_models.py`, `deploy/web.env.example`

**Interfaces:**
- Produces:
  - `WebSettings` (pydantic-free frozen dataclass) via `load_settings(env) -> WebSettings`: `SD_DATABASE_URL`, `SD_AGENT_SOCKET`, `SD_PUBLIC_HOSTNAME` (`slurmdeck.local`), `SD_CLUSTER_NAME`, `SD_CLUSTER_TZ` (IANA name, default `UTC`), `SD_MAIL_PROVIDER` (`resend`|`smtp`|`none`), `SD_MAIL_FROM`, `SD_RESEND_API_KEY`, `SD_SMTP_HOST/PORT/USER/PASSWORD/STARTTLS`, `SD_SECURE_COOKIES` (default true), plus the roadmap's fixed values.
  - `db.engine(settings)`, `db.session_scope() -> ContextManager[Session]`, FastAPI dependency `db.get_db`.
  - Tables (SQLAlchemy models, names exact):
    - `accounts(id pk, email citext unique, full_name, username unique, role enum('user','admin'), status enum('active','disabled','deleted'), linux_kind enum('hidden','shell'), uid int unique null, password_hash null, created_at, created_by_id fk null, last_login_at null)`
    - `sessions(token_hash pk, account_id fk, csrf_token, created_at, last_seen_at, ip, user_agent, acting_as_account_id fk null)`
    - `password_tokens(token_hash pk, account_id fk, purpose enum('set','reset'), created_at, expires_at, used_at null)`
    - `login_attempts(id pk, email citext, ip inet, at, success bool)` with index on `(email, at)` and `(ip, at)`
    - `applications(id pk, email citext, full_name, role_title, organisation null, contact_number, reason null, status enum('pending','approved','rejected'), created_at, ip, decided_by_id null, decided_at null, note null, account_id null)` + partial unique index on `email` where `status='pending'`
    - `allowlist(id pk, kind enum('domain','address'), value citext unique, created_by_id, created_at)`
    - `settings(key pk, value jsonb, updated_by_id null, updated_at)`
    - `audit_events(id pk, ts, actor_id null, acting_admin_id null, action, target, detail jsonb, result, source enum('web','agent','worker'))`
    - `outbox(id pk, to_addr, subject, html, text, kind, created_at, attempts int default 0, next_attempt_at, sent_at null, last_error null)`
  - Migration also creates: extension `citext`; sequence `web_uid_seq`; role `sd_agent_ro` (LOGIN, password from `SD_AGENT_DB_PASSWORD` at migrate time) with `SELECT` on the two views only; views:
    - `agent_sessions(token_hash, username, role, linux_kind, uid, status, created_at, last_seen_at, acting_as_username)` — join `sessions`→`accounts`, `acting_as_username` from `acting_as_account_id`.
    - `agent_accounts(username, role, linux_kind, uid, status, created_at, last_seen_at)` (`created_at`/`last_seen_at` are the account's, kept to match `SessionRow`).
  - Seeded `settings`: `default_time_limit="08:00:00"`, `extension_cap_hours=24`, `submit_rate_per_hour=20`, `disk_alert_percent=90`, `mail_enabled=true`, `maintenance_banner=null`, `terminal_jobs_enabled=true`, `cluster_location=""`.
- Test fixture `pg_db` (marker `pg`): fresh database per test module, `alembic upgrade head`.

- [ ] **Step 1:** Tests (`pg`): migration applies; `sd_agent_ro` can `SELECT * FROM agent_sessions` and cannot `SELECT * FROM accounts`; inserting two accounts with emails `A@x.com`/`a@x.com` violates uniqueness; two pending applications for one email violate the partial index; `nextval('web_uid_seq')` starts at 20000. And `deckagent.sessions.PgSessionStore` (Phase 1) reads a session row through the real view.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add web settings, schema, migrations and agent read-only views`.

---

### Task 2: Security primitives and web audit

**SerenEdge:** `SLURM-12`

**Files:**
- Create: `src/sdweb/security.py`, `src/sdweb/audit.py`, `src/sdweb/auth/common-passwords.txt`, `tests/web/test_security.py`

**Interfaces:**
- Produces:
  - `hash_password(pw: str) -> str` / `verify_password(hash: str, pw: str) -> bool` (argon2id, `argon2.PasswordHasher()` defaults); `needs_rehash(hash) -> bool`.
  - `password_problems(pw: str, *, email: str, username: str) -> list[str]` — messages exactly: `"Use at least 12 characters."`, `"That password is too common."`, `"Don't use your email or username."`.
  - `new_token() -> str` (`secrets.token_urlsafe(32)`); `hash_token` (re-export of `deckagent.sessions.hash_token`).
  - `normalize_email(raw: str) -> str` (strip, lowercase) and `valid_email(addr: str) -> bool` (one `@`, non-empty local, domain with a dot, no spaces, ≤ 254).
  - `record(db, *, actor_id, action, target="", detail=None, result="ok", acting_admin_id=None, source="web") -> None` writing `audit_events`.

- [ ] **Step 1:** Tests: hashing round-trip; `password_problems("short", ...)` returns the first message; a list entry returns the second; `normalize_email("  Amasha@IIT.ac.lk ") == "amasha@iit.ac.lk"`; `new_token()` ≥ 43 chars and two calls differ.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add password, token and audit helpers`.

---

### Task 3: Sign-in, sessions, CSRF, lockout, password set/reset/change

**SerenEdge:** `SLURM-13`

**Files:**
- Create: `src/sdweb/auth/__init__.py`, `src/sdweb/auth/sessions.py`, `src/sdweb/auth/routes.py`, `src/sdweb/deps.py`, `src/sdweb/app.py`, `tests/web/test_auth.py`

**Interfaces:**
- Consumes: Tasks 1–2; `sdweb.mail.enqueue` (Task 4 — this task calls it through `deps.get_mailer`, stubbed in tests).
- Produces:
  - `create_app(settings: WebSettings, agent: AgentClient | None = None) -> FastAPI`.
  - Dependencies: `current_session(request) -> SessionCtx` (401 if missing/expired; refreshes `last_seen_at`), `require_user`, `require_admin` (403), `require_csrf` (403 `csrf`). `SessionCtx(account: Account, session: SessionRowORM, raw_token: str, acting_as: Account | None)`; `effective_account` property = `acting_as or account`.
  - Endpoints (JSON):
    - `POST /api/auth/login` `{email, password}` → 200 `{account: AccountOut, csrf_token}` + cookie; 401 `{"error":"bad_credentials"}` for unknown email **or** wrong password (same timing: verify against a dummy hash); 423 `{"error":"locked","retry_after_s"}`; 429 per-IP.
    - `POST /api/auth/logout` → deletes the row, clears cookie.
    - `GET /api/auth/me` → `{account, acting_as, csrf_token}`.
    - `POST /api/auth/password/set` `{token, password}` (purpose `set` or `reset`) → marks used, sets hash, deletes all that account's sessions, signs in.
    - `POST /api/auth/password/forgot` `{email}` → always 202; enqueues reset mail only for an active account.
    - `POST /api/auth/password/change` `{current, new}` (CSRF) → kills other sessions.
  - `AccountOut{id, email, full_name, username, role, status, linux_kind}`.
  - `issue_password_token(db, account, purpose) -> str` (raw) used by Tasks 5–6.

- [ ] **Step 1:** Tests (`pg`, `TestClient`):
  ```python
  def test_login_sets_strict_cookie(client, active_user):
      r = client.post("/api/auth/login", json={"email": " AMASHA@iit.ac.lk", "password": PW})
      c = r.headers["set-cookie"]; assert "HttpOnly" in c and "SameSite=Strict" in c and "Secure" in c
  def test_unknown_email_and_wrong_password_look_the_same(client, active_user): ...
  def test_lockout_after_ten_failures_and_owner_emailed(client, active_user, outbox): ...  # 11th → 423
  def test_idle_31_minutes_logs_out(client, frozen_time): ...
  def test_absolute_12h_logs_out_even_when_active(client, frozen_time): ...
  def test_post_without_csrf_is_403(client, signed_in): ...
  def test_reset_link_single_use(client, reset_token): ...        # second use → 400 "link_used"
  def test_reset_link_expires_after_one_hour(client, frozen_time): ...
  def test_set_password_kills_existing_sessions(client): ...
  def test_disabled_account_cannot_sign_in(client, disabled_user): ...  # 401 bad_credentials
  ```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add sign-in, sessions, CSRF, lockout and password flows`.

---

### Task 4: Mail outbox, templates and the worker loop

**SerenEdge:** `SLURM-14`

**Files:**
- Create: `src/sdweb/mail/__init__.py`, `src/sdweb/mail/templates.py`, `src/sdweb/mail/senders.py`, `src/sdweb/worker/__init__.py`, `src/sdweb/worker/__main__.py`, `src/sdweb/worker/mail_task.py`, `tests/web/test_mail.py`

**Interfaces:**
- Produces:
  - `enqueue(db, *, to: str, kind: str, context: dict) -> int` — renders via `templates.render(kind, context, settings) -> (subject, html, text)`; respects setting `mail_enabled` (when false, rows are written with `sent_at` null and `last_error="mail disabled"` and never sent).
  - Kinds (this phase): `set_password` (`link`), `reset_password` (`link`), `lockout` (`until`), `application_received_admin` (`application`), `application_approved` (`link`), `application_rejected` (`note`), `account_created_admin_notice` (`username`, `created_by`). Later phases add kinds via the same registry: `templates.register(kind, subject_fn, body_fn)`.
  - Every context value passes through `html.escape` before interpolation; times rendered in `SD_CLUSTER_TZ` with its abbreviation.
  - `senders.ResendSender`, `senders.SmtpSender`, `senders.NullSender` with `send(to, subject, html, text) -> None` (raise on failure).
  - Worker loop `python -m sdweb.worker`: every 10 s, `mail_task.drain(db, sender, now)` sends due rows; on failure `attempts += 1`, backoff `min(2**attempts, 360)` minutes, gives up after 8 attempts (keeps the row with `last_error`).

- [ ] **Step 1:** Tests: a job-name-like value `<script>x</script>` appears escaped in html; `mail_enabled=false` → nothing sent; failed send schedules retry at +2 min then +4 min; template set/reset contain the link and **no** password field.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add mail outbox, escaped templates and worker sender loop`.

---

### Task 5: Account management API (admin)

**SerenEdge:** `SLURM-15`

**Files:**
- Create: `src/sdweb/accounts/__init__.py`, `src/sdweb/accounts/service.py`, `src/sdweb/accounts/routes.py`, `tests/web/test_accounts.py`

**Interfaces:**
- Consumes: `AgentClient.call` verbs `account.inspect_folder`, `account.create`, `account.attach_shell`, `account.delete` (Phase 1 Task 9); Tasks 1–4.
- Produces (`require_admin` + CSRF on writes):
  - `GET /api/admin/accounts?q=&role=&status=` → list of `AccountOut` + `uid`, `created_at`, `last_login_at`.
  - `POST /api/admin/accounts/preview` `{email, username?}` → `{suggested_username, username_valid, email_valid, existing_folder: FolderInfo | null, shell_account: {uid} | null}`.
  - `POST /api/admin/accounts` `{email, full_name, username, role, reconnect_folder: bool, attach_shell: bool}` → creates the DB row **only after** the agent call succeeds, inside one transaction holding `SELECT ... FOR UPDATE` on a per-username advisory lock: uid = `nextval('web_uid_seq')` unless `reconnect_folder` (uid = folder owner) or `attach_shell` (uid from `account.attach_shell`, `linux_kind='shell'`); then `issue_password_token(... "set")` and `enqueue("set_password")`, and `enqueue("account_created_admin_notice")` to every other active admin.
  - `POST /api/admin/accounts/{id}/disable` | `/enable` | `/reset-password` | `PATCH /api/admin/accounts/{id}` `{role?, email?, full_name?}` | `DELETE /api/admin/accounts/{id}?purge=false` (purge requires body `{"confirm": "<username>"}`).
  - `POST /api/admin/view-as/{id}` and `DELETE /api/admin/view-as` — set/clear `sessions.acting_as_account_id` on the admin's own session; refused for shell accounts and other admins.
  - Guards: admin cannot disable/delete/demote themselves; the last active admin cannot be disabled/deleted/demoted (409 `last_admin`, message "There must always be at least one active admin.").
  - Every action → `audit.record`.

- [ ] **Step 1:** Tests (agent replaced by a fake recording calls):
  ```python
  def test_create_calls_agent_then_inserts_and_mails(client_admin, fake_agent, outbox): ...
  def test_agent_failure_leaves_no_row_and_retry_works(client_admin, fake_agent_failing_once): ...
  def test_reconnect_uses_folder_owner_uid(client_admin, fake_agent_with_folder(owner_uid=2014)): ...
  def test_attach_shell_sets_kind_and_uid(client_admin, fake_agent_shell(uid=1800)): ...
  def test_last_admin_cannot_be_disabled(client_admin_only): ...   # 409
  def test_purge_requires_typed_username(client_admin): ...
  def test_view_as_sets_session_column_and_me_reports_it(client_admin, user): ...
  def test_non_admin_gets_403_everywhere(client_user): ...
  ```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add admin account management and View as user`.

---

### Task 6: Applications and the allow-list

**SerenEdge:** `SLURM-16`

**Files:**
- Create: `src/sdweb/accounts/applications.py`, `src/sdweb/accounts/allowlist.py`, `tests/web/test_applications.py`, `tests/web/test_allowlist.py`

**Interfaces:**
- Consumes: Task 5 `service.create_account(db, agent, admin, *, email, full_name, username, role, reconnect_folder, attach_shell) -> Account`.
- Produces:
  - `allowlist.matches(entries: list[AllowEntry], email: str) -> bool`; `GET/POST/DELETE /api/admin/allowlist` (admin).
  - `GET /api/public/apply-open` → `{"open": bool}` (open ⇔ allow-list non-empty).
  - `POST /api/public/applications` `{email, full_name, role_title, organisation?, contact_number, reason?, website}` (no session, no CSRF; `website` is the honeypot — non-empty ⇒ pretend success, store nothing). Limits: 5 per IP per hour, 1 pending per email (409 with "You already have an application waiting for review."). Not allow-listed ⇒ 403 with the exact refusal copy; nothing stored. Success ⇒ 201 with the exact success copy; `enqueue("application_received_admin")` to every active admin.
  - Admin: `GET /api/admin/applications?status=pending` ; `POST /api/admin/applications/{id}/approve` `{username, role, reconnect_folder}` → `create_account` then `status='approved'`, `account_id` set, `enqueue("application_approved")` (the set-password link is that mail's `link`; Task 5's separate `set_password` mail is skipped for this path); `POST /api/admin/applications/{id}/reject` `{note?}` → `enqueue("application_rejected")`. Both take `SELECT ... FOR UPDATE` on the row and 409 `already_decided` if not pending.

- [ ] **Step 1:** Tests:
  ```python
  @pytest.mark.parametrize("email,ok", [("a@iit.ac.lk", True), ("A@IIT.AC.LK", True), ("a@cs.iit.ac.lk", False),
                                        ("partner@company.com", True), ("other@company.com", False)])
  def test_matching(email, ok): assert matches([dom("iit.ac.lk"), addr("partner@company.com")], email) is ok
  def test_empty_allowlist_closes_form(client): assert client.get("/api/public/apply-open").json() == {"open": False}
  def test_refused_email_is_not_stored(client_with_allowlist): ...
  def test_honeypot_pretends_success_stores_nothing(client_with_allowlist): ...
  def test_concurrent_approve_creates_one_account(client_admin, pending_app):  # two threads → one 200, one 409
  def test_reject_sends_note(client_admin, pending_app, outbox): ...
  ```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add access applications and admin-managed allow-list`.

---

### Task 7: Frontend shell, design tokens and public pages

**SerenEdge:** `SLURM-17`

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.ts`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/styles/tokens.css`, `frontend/src/api/client.ts`, `frontend/src/api/auth.ts`, `frontend/src/app/AppShell.tsx`, `frontend/src/app/routes.tsx`, `frontend/src/app/ThemeToggle.tsx`, `frontend/src/app/ViewAsBanner.tsx`, `frontend/src/pages/SignIn.tsx`, `frontend/src/pages/Apply.tsx`, `frontend/src/pages/SetPassword.tsx`, `frontend/src/pages/ForgotPassword.tsx`, `frontend/src/pages/Placeholder.tsx`, `frontend/src/components/Panel.tsx`, `frontend/src/components/Wordmark.tsx`, `frontend/src/**/*.test.tsx`

**Interfaces:**
- Consumes: Task 3 and 6 endpoints.
- Produces:
  - `tokens.css`: the spec §6 token table verbatim on `:root` (dark), redefined under `@media (prefers-color-scheme: light)` and again under `:root[data-theme="light"]` / `:root[data-theme="dark"]`; plus `--danger`, `--warning`, `--ok` (separate from `--accent`). Tailwind theme maps `bg`, `surface`, `surface-2`, `border`, `text`, `text-dim`, `accent`, `danger`, `warning`, `ok` to the variables. Font stacks exactly as spec §6. No external font or CDN requests.
  - `api/client.ts`: `apiFetch<T>(path, init?)` sending `credentials: "same-origin"`, adding `X-CSRF-Token` from the last `/api/auth/me` or login response on non-GET, throwing `ApiError{status, code, message}`; on 401 redirects to `/sign-in?next=<path>`.
  - Routes: `/sign-in`, `/apply`, `/set-password?token=`, `/forgot-password`, `/` (home, Phase 3), `/new`, `/jobs`, `/jobs/:id`, `/files/*`, `/envs`, `/models`, `/services`, `/usage`, `/notify`, `/admin/*`. Unbuilt pages render `Placeholder`.
  - `AppShell`: left sidebar (Dashboard, New job, Jobs, Files, Environments, Models, Services, Usage, Notify, Admin for admins), top bar (cluster status slot, account menu with Change password / Sign out), `ViewAsBanner` (red, "Viewing as {username} — every action is recorded. Stop viewing") whenever `acting_as` is set.
  - `SignIn`: `> SLURM` / `DECK` wordmark, tagline "Run your GPU work on the cluster from your browser.", double-ruled `Panel`, email/password, "Forgot password", "Apply for access" (only when `apply-open`), "Download the site certificate" link to `/ca.crt`, footer `Slurm Deck · v{version} · MIT · source`.
  - `Apply`: the spec §5.4 fields, client-side required checks, shows server copy verbatim.
  - `ThemeToggle` persists `localStorage["sd-theme"]` (`light`|`dark`|absent), wrapped in try/catch.

- [ ] **Step 1:** Vitest tests: SignIn hides Apply when `open:false`; shows server error `bad_credentials` as "That email and password don't match."; ThemeToggle sets `data-theme` and survives a throwing `localStorage`; ViewAsBanner renders when `acting_as` present; `apiFetch` adds the CSRF header on POST only.
- [ ] **Step 2:** `npm test` → FAIL. **Step 3:** Implement. **Step 4:** `npm test && npm run build` → PASS, `dist/` produced. Add frontend steps to `scripts/ci.sh` (`frontend-lint` `npm run lint`, `frontend-typecheck` `npx tsc --noEmit`, `frontend-test` `npm test -- --run`, `frontend-build` `npm run build`) and Node 20 to the GitHub workflow; run `serenedge ci` → PASS. This makes the task a CI change.
- [ ] **Step 5:** Commit `<KEY>: add React shell, design tokens and sign-in/apply/password pages`.

---

### Task 8: Admin pages — Users, Requests, Application access

**SerenEdge:** `SLURM-18`

**Files:**
- Create: `frontend/src/pages/admin/AdminLayout.tsx`, `frontend/src/pages/admin/Users.tsx`, `frontend/src/pages/admin/NewUser.tsx`, `frontend/src/pages/admin/UserDetail.tsx`, `frontend/src/pages/admin/Requests.tsx`, `frontend/src/pages/admin/AppAccess.tsx`, `frontend/src/api/admin.ts`, tests alongside.

**Interfaces:**
- Consumes: Task 5–6 endpoints.
- Produces: admin sub-navigation (Requests, Users, Application access; later phases add Settings, Jobs, Usage, Cluster, Shared assets, Monitoring). `NewUser` runs `preview` on email/username blur and shows "Existing folder found — {size}, last changed {date}, owned by UID {uid}." with a required choice "This is the same person — reconnect" / "Different person — choose another username"; shows "Existing shell account found" with "Attach web account". Delete dialog: keep data (default) or purge, purge needs the username typed. View as button on UserDetail.

- [ ] **Step 1:** Vitest tests: reconnect choice is required before Create enables when a folder is found; purge button disabled until the typed username matches; Requests approve dialog pre-fills `suggested_username`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add admin users, requests and application-access pages`.

---

### Task 9: Container image, Compose, Caddy and first-admin bootstrap

**SerenEdge:** `SLURM-19`

**Files:**
- Create: `deploy/web.Dockerfile`, `deploy/compose.yaml`, `deploy/Caddyfile`, `deploy/secrets.env.example`, `src/sdweb/cli.py`, `src/sdweb/static.py`, `tests/web/test_cli.py`, `tests/e2e/test_compose_smoke.py`

**Interfaces:**
- Produces:
  - `web.Dockerfile`: stage 1 `node:20` builds `frontend/dist`; stage 2 `python:3.12-slim` installs `.[web]`, copies `dist` to `/app/static`, `USER ${SD_WEB_UID}:${SD_WEB_GID}` (build args), `CMD uvicorn sdweb.app:create_app_from_env --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*`.
  - `static.mount(app, path)` serves `index.html` for unknown non-`/api` paths (SPA fallback).
  - `compose.yaml` services: `db` (`postgres:16`, volume `pgdata`, healthcheck), `migrate` (same image, `alembic upgrade head`, runs once), `web` (port 8000 internal only, mounts `/run/slurm-deck-web/agent.sock`, `env_file: /etc/slurm-deck-web/web.env`, `/etc/slurm-deck-web/secrets.env`, `user: "${SD_WEB_UID}:${SD_WEB_GID}"`, `read_only: true`, `tmpfs: /tmp`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`), `worker` (same image, `command: python -m sdweb.worker`, `user: "${SD_WORKER_UID}:${SD_WORKER_GID}"`, same hardening), `caddy` (`caddy:2`, ports `443:443`, `80:80`, volume `caddy_data`, `Caddyfile`). No service mounts `/shared`, the Docker socket, or anything under `/etc/munge`.
  - `Caddyfile`: `{$SD_PUBLIC_HOSTNAME}` with `tls internal`; `reverse_proxy web:8000` with `flush_interval -1` and no read/write timeouts on `/api/uploads/*`, `/notebook/*`, `/tensorboard/*`, `/terminal/*`, `/ws/*`; `request_body max_size 128MB` on `/api/uploads/*` (chunk 64 MB + headroom); `handle /ca.crt` serving Caddy's root cert from the data volume; HTTP → HTTPS redirect.
  - `python -m sdweb.cli create-admin --email E --full-name N --username U` — refuses if any admin exists unless `--force`; calls agent `account.create`; prints the set-password link (does not email).

- [ ] **Step 1:** Tests: `create-admin` refuses when an admin exists; prints a URL starting `https://<SD_PUBLIC_HOSTNAME>/set-password?token=`. E2E (manual-gated, `SD_E2E=1`): `docker compose up -d`, `GET https://localhost/api/public/apply-open` (with `--insecure`) → 200; `docker compose exec web id -u` ≠ 0.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add container image, Compose stack, Caddy and first-admin CLI`.

---

## Phase exit check

- [ ] On a test VM with deck-agent from Phase 1: `docker compose up -d`, `create-admin`, open the set-password link, sign in, add an allow-list domain, apply from a second browser, approve, the applicant sets a password and signs in. Audit table shows every step.
