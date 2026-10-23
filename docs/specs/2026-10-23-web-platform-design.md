# Slurm Deck Web — Full Design

**Status:** approved by the project owner, 2026-10-23
**Date:** 2026-10-23
**Replaces:** the SSH ForceCommand TUI as the access path for normal users and
admins. Supersedes §1–4 of the v1.5.0 design (web UI), which assumed PAM
logins against real Linux accounts — this design does not. That older spec,
and every other v1.4 document, lives on the `legacy/v1.4-tui` branch
(`docs/specs/2026-08-04-v1.5.0-full-design.md` there).

Calls marked **[builder's call]** or **[my call]** were not decided by the
project owner; everything else was.

---

## 1. Intent

Today every user SSHes to the login node and is forced into a Python TUI. That
model has three problems the owner wants gone:

1. **Students need SSH accounts on the login node** just to reach a menu. Those
   accounts are the attack surface: the ForceCommand wrapper can be bypassed
   (a command containing `sftp-server` runs anything), so "no shell" was never
   really true.
2. **The TUI is the wrong tool for most of the work.** 234 of 410 recent job
   logs are JupyterLab sessions reached through hand-typed SSH tunnels and
   copied tokens.
3. **Account management is tied to Linux logins** rather than to the person.

The new platform is a **browser-only web app on the campus LAN** at
`slurmdeck.local`. People sign in with **email + password**, land on a clean
dashboard, and do everything the TUI does today from there. **Slurm still does
all workload management** — the web app never runs user work itself; it builds
and submits Slurm jobs exactly as the TUI does.

Success looks like: a student who has never used SSH gets an account, uploads a
150 GB dataset, starts a JupyterLab session on the GPU, extends it when it runs
long, and never sees a terminal, a token, or a tunnel command.

---

## 2. Goals, non-goals, anti-goals

### Goals
- Web-only access for **normal users and admins**; they have **no login-node
  account** and cannot SSH, scp, or run commands on any node.
- **Shell users** keep exactly what they have today (real login-node account,
  real shell, scp/rsync). They are the exception for fully trusted people. The
  one change for them: they lose the `docker` group like everyone else (§10.2).
- **Every TUI feature in the first version** (full list in §6).
- **Own authentication**: email + password, admin-created accounts only, plus a
  public "Apply for access" form gated by an admin-managed allow-list.
- Jupyter and TensorBoard open in a **new browser tab** with no token or tunnel.
- Users **extend their own sessions up to an admin-set cap**.
- **Large uploads (100s of GB)** through the browser, resumable.
- Runs on the **LAN only**, entirely on the **login node**, installed and
  managed by **slurmadmin**, with the user-facing parts in containers (see §4, §9).
- Open-source friendly: nothing site-specific hardcoded.

### Non-goals (v1)
- Internet exposure. Cloudflare tunnel / public access is out of scope.
- Google or any SSO login.
- Per-user storage quotas (explicitly rejected — storage is one shared pool).
- Self-service signup without admin approval.
- Multi-cluster support.
- Migrating old accounts or old job history into the new database (see §12).
- Two-factor auth (worth adding later, especially for admins).

### Anti-goals — failure even if it "works"
- **All jobs running as one shared Linux account.** Per-person separation of
  files and Slurm fair-share must survive the move to the web.
- **Any web user able to read another user's files, notebooks, or logs.**
- **A web-app compromise that hands out root** on the GPU host or NFS server.
- **Shell users disrupted** by the change (beyond losing Docker, §10.2).
- Students losing their existing `/shared/users/<name>` work.

---

## 3. Current system (what this builds on)

From the live inspection (2026-10-23):

| Machine | Role |
|---|---|
| **GPU host** `iit-MS-7E06` — physical, LAN `10.35.4.100`, virbr0 `192.168.122.1` | slurmd, NFS server for `/shared` (`/mnt/nvme_storage/shared`, ext4, 1.7 TB, NFSv4 to `192.168.122.0/24`, root_squash), Docker, Ollama, munge, slurm-deck-stats. 32 cores, 62 GB RAM, RTX 5090. |
| **login-node** — KVM VM `192.168.122.10` | slurmctld, slurmdbd + MariaDB, slurm-deck-audit, sshd (ForceCommand TUI), cloudflared, `/opt/slurm-deck`. |
| **systems-research** — KVM VM, shut off | unused |

Slurm: one partition `gpu` (1-day max), one node, `Gres=gpu:1,shard:4`,
`select/cons_tres` + `CR_Core_Memory`, cgroups with ConstrainCores /
ConstrainRAMSpace / ConstrainDevices on, priority/multifactor (fairshare 100000,
QoS 10000, age 1000), backfill. Every user has the `default` account and
`normal` QoS.

### Where the existing code is

`main` and `dev` start empty apart from this design. The whole v1.4 codebase,
with its history, tests and docs, is on the **`legacy/v1.4-tui`** branch, and
the live cluster keeps running it from there until cutover (§12). Wherever this
document says "reuse X", it means **bring X over from `legacy/v1.4-tui` into
the new codebase, with its tests**, not import it from a running install.

**[my call] Port, don't rewrite, the parts that are already pure logic and
proven on this cluster.** Fix the defects the 2026-10-23 audit found while
porting them:

| From `legacy/v1.4-tui` | Used for |
|---|---|
| `slurmdeck/launchspec.py`, `pods.py` | job intent defaults, pod → CPU/RAM sizing |
| `slurmdeck/jobs.py` (`render_sbatch`, `render_notebook_sbatch`, `render_tensorboard_sbatch`, readiness-marker and free-port snippets) | generating job scripts (with the §6.4 fixes) |
| `slurmdeck/slurm.py` (squeue/sacct/scontrol parsing) | deck-agent's Slurm reads |
| `slurmdeck/validate.py` (jails, time/name/arg cleaning, QoS checks) | input validation in `web` and deck-agent |
| `slurmdeck/connect.py` | notebook readiness and node/port/token parsing |
| `slurmdeck/upload.py` (zip extraction safety), `setup.py` (post-install package verification), `envbuilder.py` | extraction and env builds |
| `envs/specs/*.yml`, `deploy/images/*.def` | prebuilt envs and Apptainer images (add the §6.7 version bounds) |
| `deploy/resize-pods.sh` | pod resize |
| `deploy/slurm-deck-mailer` | Slurm job BEGIN/END/FAIL email (MailProg), with HTML escaping |
| `deploy/slurm-deck-stats-writer` + `.service` | the GPU-host stats file the dashboard reads (run as a dedicated service account, §10.8) |
| `deploy/slurm-deck-adduser.sh` / `deluser.sh` | logic for the GPU-host helper (with strict username checks and no `docker`) |

The Rich/questionary presentation modules (`menu.py`, `wizard.py`,
`review.py`, `dashboard.py`, `admin.py`, `ui.py`, `splash.py`) are **not**
ported; their behaviour is the reference for what the web screens must do.

---

## 4. Architecture

### 4.1 Machines

```
 LAN (campus)                 GPU host (physical, 10.35.4.100 / 192.168.122.1)
 browser ──HTTPS:443──▶ port-forward 443 ─▶ login-node VM (192.168.122.10)
                                             ├─ Docker Compose (installed and managed
                                             │  by slurmadmin; containers run as the
                                             │  unprivileged `sdweb`/`sdworker` accounts):
                                             │    caddy, web, worker, db
                                             │        │ Unix socket, fixed verbs
                                             │        ▼
                                             ├─ deck-agent (systemd, root) —
                                             │  Slurm, storage, accounts
                                             ├─ slurmctld, slurmdbd, munge
                                             ├─ sshd (SHELL USERS + sysadmins only)
                                             └─ /shared (NFS from the GPU host)
                                                      │ restricted SSH,
                                                      ▼ fixed commands only
                                GPU host: slurmd, NFS server, GPU, jobs run here
```

**Decided: the whole platform runs on the login node.** The installer treats
the login node as the host. There is no separate web VM.

**Decided: slurmadmin installs and manages it (option 1).** The code lives
under slurmadmin's install directory, **`/opt/slurm-deck-web`** **[my call]**,
owned by slurmadmin. It must not be `/opt/slurm-deck`: that is the live v1.4
TUI clone, which keeps running side by side until cutover (§12). slurmadmin and runs the installer, upgrades, backups and
`docker compose` commands. **The running containers do not run as
slurmadmin:** they run as a dedicated unprivileged service account, `sdweb`
(nologin, no sudo, no Slurm association, not in `docker`/`gpuusers`/
`gpuadmins`). Reason: slurmadmin owns `slurm.conf`/`gres.conf` and runs
`resize-pods.sh`; anyone who can edit `slurm.conf` can make Slurm run scripts
as root on the GPU host, so a website bug must never land as slurmadmin.

**What the website can and cannot reach.** The `web`/`worker`/`caddy`/`db`
containers run as `sdweb` with no host mounts except their own data volume,
the secrets file, and deck-agent's socket. They cannot read `munge.key`
(root-only), `slurm.conf` edit rights, `/shared`, or `/etc/shadow`, and have no
Docker socket. Escaping a container lands an attacker as `sdweb`, which can do
nothing but talk to deck-agent — and deck-agent still demands a valid user
session for every request (§4.3).

**deck-agent** is the one privileged service (root, systemd). It handles:

- **Slurm:** submit, cancel, extend, list jobs; `sacct`/`squeue`/`scontrol`
  reads; `sacctmgr` for associations and QOS; drain/resume; pod resize (it
  runs `resize-pods.sh` as slurmadmin through the existing sudoers rule).
- **Storage:** every file operation, uploads, downloads, extraction, job-log
  reads, disk-usage scans — on the login node's `/shared` NFS mount, acting
  *as the user*. `/shared` is the GPU host's `/mnt/nvme_storage/shared`, so this
  is the same storage the jobs see.
- **Accounts:** creates/removes the hidden account on the login node.

**What still has to happen on the GPU host, and how.** The NFS export uses
`root_squash`, so root on the login node is `nobody` on `/shared`. Acting as
the user over NFS works (NFS checks that user's UID — exactly what we want),
but these steps need real root on the GPU host:

- creating the hidden account on the GPU host (jobs run there, so the UID must
  exist there);
- creating a new user's `/shared/users/<name>` and `/shared/jobs/<name>`
  folders with the right owner, mode 2770 and the `gpuadmins` ACL;
- archiving (`.offboarded`) or purging a departed user's data;
- removing the account on the GPU host.

deck-agent does these over **restricted SSH to the GPU host**, the mechanism
`slurm-deck-adduser`/`deluser` already use, but locked to a single
forced-command script on the GPU host that accepts only those named operations
with validated arguments (no general shell, no `NOPASSWD: ALL`). Nothing else
runs permanently on the GPU host.

**Network reachability.** The login node sits on libvirt's NAT network. The
GPU host forwards TCP 443 (and 80 → 443 redirect) to the login node, alongside
the existing 2225 → sshd forward.

**Name.** `slurmdeck.local` is resolved by mDNS: the GPU host runs avahi and
publishes `slurmdeck.local → 10.35.4.100`. Windows 10+, macOS and most Linux
desktops resolve `.local` via mDNS. Sites with their own DNS can instead add an
ordinary record; the hostname is a setting (`PUBLIC_HOSTNAME`).

**HTTPS.** Passwords cross the LAN, so HTTPS is mandatory. `.local` cannot get
a public certificate, so **[my call]** Caddy runs its internal CA and issues the
certificate; the admin distributes the CA's root certificate once (download link
on the sign-in page + install instructions), after which browsers show no
warning. A site with a real domain can switch Caddy to a public certificate by
changing one setting.

**Login-node sizing [my call].** The login node now runs slurmctld, slurmdbd,
MariaDB, Postgres, the web stack, and carries all upload/download traffic.
Raise it from 3.8 GB to at least **4 vCPU / 12 GB RAM** and add swap before
go-live (it already OOM'd once at 3.8 GB with no swap). This RAM comes from the
GPU host's 62 GB; GPU-pod RAM is derived from the GPU host's own reported
total, so jobs are unaffected as long as the host keeps enough free.

### 4.2 Components (all on the login node)

| Component | Runs as | Job |
|---|---|---|
| **caddy** | container, `sdweb` | TLS, HTTP→HTTPS, reverse proxy to `web`, static assets, large-body pass-through for uploads |
| **web** | container, `sdweb` | FastAPI app: REST + WebSocket API, auth, sessions, Jupyter/TensorBoard/terminal proxy, upload endpoint (streams chunks on to deck-agent), serves the frontend build |
| **db** | container, `sdweb` | PostgreSQL: accounts, password hashes, sessions, applications, settings, job index, audit log |
| **worker** | container, `sdworker` | background tasks: expiry warnings, notify-when-free, disk alerts, session cleanup, email outbox |
| **deck-agent** | systemd service, root | all Slurm, storage and account verbs (§4.3) |
| **gpu-host helper** | forced-command script via SSH, on the GPU host | only the GPU-host steps listed in §4.1 |

Management (install, upgrade, `docker compose`, backups, logs) is done by
**slurmadmin**. slurmadmin is a sysadmin account and is exempt from the
Docker-group removal in §10.2.

**[my call] Why deck-agent is not a container.** It must switch to each user's
real UID (that is what keeps per-user separation) and reach munge, the Slurm
binaries, the `/shared` mount and `useradd`. From a container that needs
CAP_SETUID/SETGID, host `/etc/passwd`, the munge socket and the NFS mount all
passed in — a container in name only, and harder to audit than a small systemd
service. Everything user-facing is containerised.

### 4.3 deck-agent (privilege boundary)

- Listens on a **Unix socket** on the login node; accepts connections only
  from the `sdweb` UID (the `web` container) and the `sdworker` UID (the
  `worker` container) — socket mode + SO_PEERCRED. **[my call]** The worker
  runs as its own unprivileged account, `sdworker`, so deck-agent can tell the
  two apart.
- **Background tasks have no user session**, so the worker gets a separate,
  narrow allowance: `sdworker` may call only read-only, cluster-wide verbs
  (`cluster.status`, `cluster.queue`, `cluster.disk_free`, `job.time_left_all`)
  that never act as a user and never touch file contents. Everything it then
  sends (expiry warnings, notify-when-free, disk alerts) goes out as email
  from the worker itself. It can never submit, cancel, extend or read files.
- **Identity is not taken from `web` on faith.** Each request carries the
  user's raw session token. deck-agent hashes it and checks it against the
  sessions table through a **read-only** DB role to get the username and
  role. A compromised `web` container cannot act as a user without holding that
  user's live session. Upload chunks reuse a short-lived per-upload grant
  issued after one full check, so this is one lookup per upload, not per chunk.
- **Residual risk, stated plainly:** an attacker who takes over the `db`
  container (or `sdweb`) could forge session rows, i.e. act as any *normal*
  web user. deck-agent bounds what that buys: it only ever acts as UIDs in the
  web-user range (never root, never system or sysadmin UIDs including
  slurmadmin, never shell users other than an attached account acting as
  itself), only within those users' folders, and only through the fixed verbs.
  Cluster root, munge and `slurm.conf` stay out of reach. **[builder's call /
  follow-up]** sign session records with a key held only by deck-agent so
  forged rows are rejected, if this risk proves too high.
- **Verbs.** Jobs: `job.submit`, `job.cancel`, `job.extend`, `job.list`,
  `job.show`, `history`. Files: `fs.list`, `fs.stat`, `fs.read`,
  `fs.write_chunk`, `fs.finalize_upload`, `fs.mkdir`, `fs.rename`, `fs.delete`,
  `fs.extract`, `fs.download_stream`, `fs.free_space`, `joblog.read`.
  Cluster (read-only, for any signed-in user and for the worker):
  `cluster.status` (pods, GPU/CPU/RAM from the stats file and `scontrol`),
  `cluster.queue` (who's running: username, state, pods, time only),
  `cluster.disk_free`. Accounts: `account.create`, `account.disable`, `account.enable`,
  `account.delete`, `account.link_folder`. Admin: `admin.qos_*`,
  `admin.drain`, `admin.resume`, `admin.pods_resize`, `admin.service_status`,
  `admin.disk_usage`, `admin.publish_shared`.
- For every user-scoped verb deck-agent **forks, drops to that user's uid/gid
  (setgroups+setgid+setuid), then acts**, so the kernel and NFS enforce the
  same permissions they enforce for that person today. Paths are additionally
  checked against that user's allowed roots (reuse `validate.py` jails).
- `job.submit`: as the user, write the job folder and `job.sbatch` under
  `/shared/jobs/<user>/`, then run `sbatch`.
- `job.extend` runs `scontrol update` as root (Slurm only lets root/operator
  raise a TimeLimit) **after** checking: job belongs to the user (or caller is
  admin), new total ≤ extension cap, new total ≤ partition MaxTime.
- Admin verbs require the session's account to have the admin role, checked by
  deck-agent from the DB, not from `web`.
- **View as user (§5.7):** an admin's session may name a target user; deck-agent
  then acts as that target's UID, but only after confirming the session is an
  admin's, and audits every call as "admin X acting as Y".
- Every verb is written to the audit log (actor, target, verb, sanitised
  arguments, result) in a root-owned local log as well as the DB, so a
  compromised web stack cannot erase deck-agent's record.
- Built to avoid the audit daemon's known defects: a bounded thread pool (no
  single slow request blocks others), a whole-request deadline, strict payload
  type validation, and no exception path that can kill the process.
- The old `slurm-deck-audit` daemon is retired for web users; its useful parts
  (SO_PEERCRED, WAL SQLite habits, mail kill-switch) carry into deck-agent and
  the worker.

### 4.4 Data flow examples

**Submit a job:** browser → `POST /api/jobs` → `web` validates with
`launchspec`/`validate` and renders the sbatch text with `jobs.render_*` →
deck-agent (as user) creates `/shared/jobs/<user>/<name>_<ts>/`, writes
`job.sbatch` and runs `sbatch` → job id back → `web` indexes it in the DB and
pushes a WebSocket update.

**Open a notebook:** browser → `/notebook/<jobid>/` → `web` checks session
owns job (or admin) → deck-agent `joblog.read` returns node/port/token from
the job's `.out` (reuse `connect.parse_connect`) → `web` reverse-proxies HTTP +
WebSocket to `http://<node>:<port>/notebook/<jobid>/` with the token added
server-side. Jupyter itself runs on the GPU host inside the Slurm job.

**Upload:** browser → tus chunks → `web` streams each chunk straight through to
deck-agent, which writes it (as the user) to a staging file on `/shared`
(NFS → GPU host's NVMe). No chunk is stored in the containers.

---

## 5. Identity, accounts and roles

### 5.1 Roles

| Role | Web | Login-node SSH | Notes |
|---|---|---|---|
| **user** | yes | **no** | the default |
| **admin** | yes, plus admin panel | **no** | admin is a web role, not a Linux login |
| **shell** | optional **[my call]** | yes, real shell | created by an admin by hand as today (`slurm-deck-adduser --shell-user`); unchanged |

**Shell users with a web account [my call].** A shell user may also get a web
account. When an admin creates one for a username that already exists as a
shell user, the platform **attaches** to the existing real Linux account — no
hidden account, no `nologin`, no `webusers` group, shell and groups left
exactly as they are. Their jobs then appear normally in the web views.

Sysadmin accounts (`root-daham`, `iit`, `slurmadmin`) are outside this system
and unchanged.

### 5.2 Hidden Linux accounts (decided: "go with your guess")

Each web account (user or admin) gets a **hidden Linux account** with the same
username and UID on the GPU host and the login node:

- no password (locked), shell `/usr/sbin/nologin`, never allowed by sshd
  (`AllowGroups` on the login node lists only shell users and sysadmins;
  hidden accounts go in a `webusers` group that sshd denies);
- member of `gpuusers` (for the existing job-folder and GPU-access model);
- **not** a member of `docker` (root-equivalent) or `gpuadmins` on any node;
- a Slurm association (`default` account, `normal` QoS) so fair-share,
  accounting and QoS limits work per person exactly as today.

Why it must exist: Slurm runs every job as a real UID, `slurmctld` resolves
that UID to a name for accounting, and NFS permissions are per UID. One shared
account would break file privacy and fair-share — an anti-goal.

Creation is done by deck-agent: it creates the account (same UID, nologin,
locked, `webusers`) on the login node and the Slurm association, and calls the
GPU-host helper over restricted SSH to create the same account there plus the
user's folders and ACLs (§4.1). This is the same shape as `slurm-deck-adduser`
today, with the GPU-host side narrowed to fixed commands; the script stays for
shell users. **[builder's call]** whether deck-agent reuses the script's logic
or ports it to Python; either way the UID must be free on both nodes.

**UID reuse fix:** UIDs are allocated from a monotonic counter stored in the
database (never "highest existing + 1"), so deleting the newest account can
never hand its UID — and its files — to the next new person. Reconnecting an
old folder (§5.5) is the *only* way a UID is reused, and it requires admin
confirmation.

**Admin file access [my call].** Admins' hidden accounts are *not* in
`gpuadmins`. Instead a dedicated service account, `sd-ops` (same UID on
both nodes, nologin, member of `gpuadmins`), is the identity deck-agent
drops to for admin file verbs: reading any user's job logs, disk-usage scans,
renaming to `.offboarded`, purge, and publishing into the shared read-only
areas. The shared areas (`/shared/envs`, `models`, `datasets`, `scripts`,
`images`) are owned `sd-ops:gpuadmins`, mode 2775 — admin-write via `sd-ops`,
read for everyone. Operations that need real root on the files (creating a new
user's folders with the right owner, purging data owned by a departed UID) run
through the GPU-host helper (the NFS server, where root isn't squashed), and
only as the fixed account operations listed in §4.1.

### 5.3 Authentication

- **Email + password.** Email is the sign-in identifier; usernames are internal
  (used for Linux/Slurm/folders) and shown in the UI.
- Passwords hashed with **argon2id**; minimum 12 characters; checked against a
  small common-password list.
- **Sessions:** random 256-bit token, stored hashed in the DB; cookie
  `HttpOnly; Secure; SameSite=Strict`; 30-minute sliding expiry, 12-hour
  absolute cap (the session design from the v1.5.0 spec §1 carries over).
  Logout deletes the row. Changing a password or disabling an account kills
  all that account's sessions.
- **CSRF:** SameSite=Strict plus a per-session CSRF token on state-changing
  requests.
- **Brute force:** per-account and per-IP rate limits on sign-in; after 10
  failures in 15 minutes the account is locked for 15 minutes and the owner is
  emailed.
- **Password set/reset:** one-time links, valid 24 h (set) / 1 h (reset),
  single use, stored hashed.
- **No passwords in email, ever** (today's welcome email mails a password —
  this stops).

### 5.4 Account creation paths

**A. Admin creates directly.** Admin panel → Users → New user: email, full
name, username (suggested from the email, editable), role (user/admin). Any
email is allowed here — the allow-list (§5.6) does not apply. Result: hidden
Linux account + Slurm association + `/shared/users/<username>` and
`/shared/jobs/<username>` (2770, owner + `gpuadmins`, as today) + "set your
password" email.

**B. Apply for access (public form).** On the sign-in page, an
**Apply for access** button opens a form:

| Field | Rule |
|---|---|
| Email | required, valid format, must match the allow-list |
| Full name | required |
| Role / position | required free text (e.g. undergraduate, researcher, industry partner) |
| Organisation | optional **[my call]** — "company role" suggests outside applicants |
| Contact number | required |
| Reason / project (short) | optional **[my call]** — helps admins decide |

- Rate limited per IP and per email; one open application per email; a simple
  honeypot field against bots.
- If the email doesn't match the allow-list: refused with "Applications from
  this email aren't open — contact the cluster admin." No record is kept.
- On submit: applicant sees "Application received — you'll get an email once an
  admin reviews it"; all admins are emailed; the request appears under
  **Admin → Requests**.
- Admin **Approve**: chooses username + role (user/admin) → same as path A.
  **Reject**: optional note → applicant gets a polite email including the note.
- Shell accounts are never granted through this form.
- Applications and decisions are audited and kept (approved/rejected history).

### 5.5 Reconnecting existing folders (decided)

When an admin creates or approves an account whose username already has a
folder in `/shared/users/`:

- The panel shows it before anything is created: "Existing folder found —
  142 GB, last changed 3 Sep, owned by UID 2014."
- Admin confirms it is the same person → the hidden account is created **with
  that UID**, so the folder and the matching `/shared/jobs/<username>` folder
  work immediately, with no copying or permission rewrite.
- Admin says it's a different person → must pick another username; the old
  folder is untouched.
- Matching is by username with human confirmation — never automatic, because a
  wrong match hands one person's files to another.

### 5.6 Application allow-list (admin panel)

**Admin → Settings → Application access**: a list of entries, each either a
**domain** (`iit.ac.lk` — any address ending `@iit.ac.lk`) or a **single
address** (`partner@company.com`). Add/remove any time; every change audited.

- **Empty list = Apply form switched off** **[my call — owner skipped the
  question]**; the button is hidden.
- Fresh installs seed the list from the installer (an install-time value,
  not a hardcoded domain), so other sites aren't stuck with IIT's.
- Matching is case-insensitive on the domain part, exact on single addresses;
  subdomains don't match unless listed.

### 5.7 Account lifecycle (admin)

Disable (blocks sign-in, kills sessions, cancels nothing), enable, reset
password (sends reset link), change role, change email, delete. **Delete**
cancels the person's jobs, removes the hidden accounts and Slurm association,
and by default **keeps** their folder renamed `<username>.offboarded` (as
today); "purge data" is a separate, typed-confirmation action. The deletion
logic must validate the username strictly and refuse anything that resolves
outside `/shared/users/` (today's `slurm-deck-deluser` does not).

**View as user [replaces "Log in as user"]:** an admin can open the dashboard
as another user to see exactly what they see. A red banner shows it the whole
time; every action taken is audited as "admin X acting as Y".

---

## 6. The dashboard — features (all in v1)

Layout **[builder's call within these rules]**: left sidebar (Dashboard, New
job, Jobs, Files, Environments, Models, Services, Usage, Notify, plus Admin for
admins), top bar with cluster status line and account menu. Desktop-first; usable on a tablet; phone is view-only good enough.

**Visual identity** (carried over from the v1.5.0 spec's design system, which
extends the TUI splash screen's look rather than a generic SaaS style):

- **Color tokens** as CSS custom properties, never hardcoded in components:

  | Token | Dark | Light | Use |
  |---|---|---|---|
  | `--bg` | `#0A0E13` | `#F3F6F8` | page ground |
  | `--surface` | `#12181F` | `#FFFFFF` | panels, cards |
  | `--surface-2` | `#1A222C` | `#EEF2F5` | inputs, recessed areas |
  | `--border` | `#26313D` | `#D7DEE5` | hairlines |
  | `--text` | `#E7ECF1` | `#16202B` | primary text |
  | `--text-dim` | `#7E8CA0` | `#5B6B7C` | secondary text, labels |
  | `--accent` | `#3FD9E8` | `#0E93A3` | the product's cyan (deepened in light mode for contrast) |

  Error and warning colors are separate tokens and never reuse `--accent`.
- **Type:** system font stacks only, no CDN or web fonts (the LAN may have no
  internet). Wordmark/display: `ui-monospace, "SF Mono", "Cascadia Code",
  "JetBrains Mono", Consolas, "Roboto Mono", monospace`. UI text:
  `-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`.
- **Dark/light:** dark is the default on `:root`; `prefers-color-scheme: light`
  redefines the tokens; an in-app toggle (`:root[data-theme=...]`, remembered
  in `localStorage`) overrides the OS either way.
- **Motifs:** wordmark `> SLURM` in text color with `DECK` in accent; primary
  containers use a double-ruled top border (the TUI's `box.DOUBLE_EDGE`). Every
  screen reuses these; no per-screen visual language.
- **Sign-in page:** wordmark, one-line tagline, the double-ruled panel with
  email/password, "Forgot password", **Apply for access** (when the allow-list
  is non-empty), the CA certificate download link (§4.1), and a footer with
  product name, version, license and source link.

### 6.1 Home dashboard
- **Cluster strip:** GPU pods in use / total (the colored pod blocks from the
  splash), GPU util and VRAM, CPU, RAM — live (WebSocket, from the existing
  `.gpu_stats.json` + `scontrol` reads).
- **Maintenance banner** when an admin has set one.
- **My jobs** cards: Queued → Starting → Running → Ended, time used / limit,
  pods, with buttons: Open (notebook/TensorBoard/terminal), Logs, Extend,
  Cancel, Rerun.
- **Who's running:** other running jobs shown as username + pods + time left
  (today's status line shows all users' running jobs; keep it).
- **Disk:** total `/shared` used / free.

### 6.2 New job (replaces the wizard + review hub)
Three steps, mirroring the TUI's intent → intake → hub flow:

1. **What are you running?** Notebook (JupyterLab) · Script (train, fine-tune,
   inference, custom) · Terminal session · Smoke test.
2. **Pick inputs:** script from the jailed file picker (or upload one inline);
   environment (prebuilt / my envs / container image); data or model path
   (file picker or HuggingFace repo id); args; Python packages to pre-install.
3. **Review & launch** — an editable summary, like the TUI's review hub:
   pods (stepper, with live availability and the VRAM-is-shared caveat with the
   estimated share), CPU/RAM shown (derived from pods via `pods.py`), time
   limit (default **8 h**; at submit time it can't exceed the QoS's max wall
   time, which the old setup set to 8 h for `normal` — verify the live value;
   going further is what Extend is for, up to the cap in §6.10), email notifications
   on/off, Advanced (job array, dependency on another job), "Save as
   template", and a **Preview script** toggle that shows the exact sbatch.
   Validation runs live (QoS limits, pod ceiling, time cap) with plain-language
   errors before submit. **[my call]** It also warns when the chosen
   environment lacks a package the script imports (the `tensorboard` failure
   in sanuth's slurm-152), as a warning, not a block.

**Templates** are **per-user** (stored under the user's own area or in the DB
keyed by user), not the current global 0666 directory. Built-in presets remain.

**Rerun** any past job from Jobs → History pre-fills this flow.

### 6.3 Jobs
- **Queue:** all jobs on the cluster (others' shown without names of their
  files/scripts — username, state, pods, time only).
- **Mine:** running + pending with full detail.
- **History:** from `sacct` (filters: state, date range, type), with rerun.
- **Job detail page:** state timeline, the sbatch script, resources, exit code,
  **live log viewer** for `.out`/`.err` (streams while running, search,
  download, wraps tracebacks literally — the lesson from incident 116 that the
  top of the log matters), and the action buttons.
- **Cancel** (own jobs; admins any).
- **Extend** — see §6.10.

### 6.4 Notebooks, TensorBoard and terminal sessions (decided: new tab)
- When ready, **Open** opens a **new browser tab** at
  `https://slurmdeck.local/notebook/<jobid>/` (TensorBoard:
  `/tensorboard/<jobid>/`, terminal: `/terminal/<jobid>/`).
- The platform injects the Jupyter token server-side; the user never sees it.
  Jupyter is launched with `--ServerApp.base_url=/notebook/<jobid>/` so its own
  links work behind the proxy.
- The proxy checks the signed-in session owns the job (or is admin) on **every
  request and WebSocket upgrade**; a guessed URL from someone else is refused.
- Until ready the tab shows "Starting your session…" and auto-continues; after
  the job ends it shows "This session has ended" with a link back.
- **GPU-host firewall:** the Jupyter/TensorBoard/terminal port range on the GPU
  host accepts connections **only from the login node's IP** (where the web
  proxy runs). Normal users have no login-node account, so the only other
  people who can reach those ports are shell users and sysadmins on the login
  node, who keep tunnelling to their own sessions as today **[my call]**. Each
  session still requires its own token, so a shell user can't open someone
  else's. This closes today's hole where any user could tunnel to anyone's
  TensorBoard.
- **TensorBoard** also gets a token, proxied the same way.
- **Terminal session [my call]** (replaces the TUI "shell" intent and the
  "Advanced SLURM shell", keeping the "all TUI features" goal): a job that runs a terminal server inside the Slurm allocation
  on the GPU host, as the user, opened in a browser tab (xterm.js).
  **[builder's call]** which terminal server (e.g. ttyd, or JupyterLab's
  terminal-only mode). It is inside a Slurm allocation with cgroup limits, same
  as a Jupyter terminal today — this is not a login-node shell, so it doesn't
  break "no commands on any node" outside a job. Admins can turn the terminal
  job type off in Settings if they want users to have notebooks only.
- Jupyter launch fixes from the `.err` analysis ship here:
  `--FileContentsManager.delete_to_trash=False` (fixes the `.Trash-N` 500s),
  explicit `websocket_ping_interval`/`websocket_ping_timeout` (fixes the 293×
  warning; keeps proxied sockets alive), and **JupyterLab always launched from
  the shared `data-science` env** with the user's chosen env registered as the
  kernel — never `pip install --user jupyterlab` into system Python (fixes the
  PEP 668 / "JupyterLab missing" failures).
- Job scripts set `HOME` explicitly from the user's passwd entry and submit
  with a clean environment (fixes the `/home/slurmadmin` leak in slurm-166).

### 6.5 Files
- **File manager** over the user's own area (`/shared/users/<name>`) plus
  read-only shared areas (`/shared/datasets`, `/shared/models`, `/shared/envs`)
  — the same jail as `validate.user_browse_roots`.
- List (sortable, sizes, modified), new folder, rename, move, delete (with
  confirmation; no trash), preview text/images/CSV head, small-file text editor.
- **Download** a file, or a folder as a streamed zip.
- **Upload** — §6.6.
- **Extract** zip / tar(.gz) in place, with the path-traversal checks that
  `upload.py` already has.
- **Job outputs** at `/shared/jobs/<name>` browsable read-only from here too.
- Storage is **one shared pool, no per-user quota** (decided). Folders stay
  **private: owner + admins only** (decided).

### 6.6 Large uploads (100s of GB)
- **Resumable chunked upload** using the tus protocol (client: Uppy or
  tus-js-client; server: tus endpoint in `web`).
- Chunks (e.g. 64–100 MB) stream straight to a staging file **on `/shared`**
  through deck-agent as the user onto `/shared` — never buffered in memory,
  never written inside the containers. Finalize = atomic rename into the target folder.
- Pause/resume, survives a dropped connection or a closed laptop lid; resuming
  after closing the browser works within 24 h.
- **Folder upload** supported; the UI recommends archiving folders with many
  small files ("Zip first — 1 million small files upload far slower than one
  archive") and offers extract-after-upload.
- Before starting, checks free space on `/shared` and refuses if the upload
  wouldn't fit (shared-pool protection, not a quota).
- Expected speed on wired gigabit ≈ 100–115 MB/s (≈ 15–20 min per 100 GB),
  similar to scp. Every byte passes through the `web` container and deck-agent
  on the login node, then over NFS (virbr0) to the GPU host's disk. That
  internal link is virtual and fast; the login node's CPU/RAM is the likely
  limit, hence the sizing in §4.1. Measure early.
- Caddy and `web` configured for unlimited request duration on the upload
  route and no body-size cap per chunk beyond the chunk size.

### 6.7 Environments
- **Prebuilt** environments (`envs/specs/*.yml`) — list, see contents, admins
  install/rebuild them.
- **My environments** — build a conda env or venv from a package list or
  `requirements.txt`. **Builds run as a Slurm CPU job** on the GPU host, not on
  the login node (it OOM'd on big installs before), with
  the build log streamed in the browser and the same post-install package
  verification `setup.py` does today (the lesson from incident 116).
- **Container images** — list `/shared/images/*.sif` (Apptainer), use in jobs.
- Env specs get upper bounds on fast-moving libraries (e.g. `transformers<5`)
  — the `group_by_length` / TRL breakages came from unbounded pins.
- `/shared/envs` becomes **admin-writable only**; users' own envs live in
  their own area (`/shared/users/<name>/envs`).

### 6.8 Models
- Model library: list downloaded models, sizes, who downloaded.
- **Download from HuggingFace** by repo id, optional token for gated models
  (stored per user, encrypted at rest). Downloads **run as a Slurm job**
  (same reason as env builds), with progress in the browser; resumable;
  `HF_HUB_DISABLE_XET=1` as today.
- Shared models in `/shared/models` are admin-published; users' own downloads
  go to their area unless an admin publishes them.

### 6.9 Services
- "My running services": running notebooks, TensorBoards, terminals with
  Open / Stop.
- **Start TensorBoard** on a log directory in the user's area.

### 6.10 Extending a session (decided: users, up to a cap)
- **Extend** on any running job the user owns (all job types, not only
  notebooks **[my call]**): +1 h, +2 h, +4 h choices.
- **Cap** = admin setting "maximum total hours per job" (original + extensions),
  never above the partition MaxTime (currently 1 day). Admins can extend past
  the cap.
- Refusals are explained ("This would take the job to 26 h; the limit is
  24 h.").
- **Server-side warning** at 30 min before the limit: email + dashboard banner,
  both with an Extend button (the email links to the job page). Today's warning
  only fires if the TUI happens to be open, and tells users to press a key that
  no longer works.
- Every extension audited.

### 6.11 Usage & accounting
- Personal: GPU-hours, CPU-hours, jobs by state over 7/30/90 days (from
  `sacct`).
- Hardware stats page (today's "Hardware stats").
- Cluster status page (today's "Cluster status" / health check).

### 6.12 Notify when free
- Subscribe "email me when N pods are free"; one-time; unsubscribe/change.
- Checked by the `worker` on a timer; subscriptions stored in the DB per user
  (not today's world-writable JSON file), always sent to the account's own
  email.

### 6.13 Smoke test
- One-click tiny GPU job that checks the environment, CUDA, and the user's
  folders; shows pass/fail with the log.

---

## 7. Admin panel (all in v1)

| Section | Contents |
|---|---|
| **Requests** | pending applications (approve with username+role / reject with note), history |
| **Users** | list, search, create, disable/enable, reset password, change role/email, delete (keep or purge data), reconnect folder, View as user |
| **Application access** | the allow-list (§5.6) |
| **Settings** | extension cap, default time limit, job submission rate limit, mail on/off kill-switch, maintenance banner text, cluster name/location, public hostname, timezone |
| **Jobs** | all users' queue and history, cancel/extend any job, read any user's job logs |
| **Usage** | cluster usage by user (GPU-h, CPU-h, jobs), disk usage by user (scanning **both** `users/` and `jobs/` — today only `jobs/` is counted) |
| **Cluster control** | drain node (with "cancel running jobs" option), resume node, QOS / limits editor (max wall, max GPUs/pods per user, priority), pods (occupancy grid + resize via the existing `resize-pods.sh` path) |
| **Shared assets** | publish/remove datasets, models, envs, images in the shared read-only areas; install/rebuild prebuilt envs |
| **Monitoring** | audit log (filter by user/action/date), service health (slurmctld, slurmd, slurmdbd, mariadb, web stack, deck-agent), mail delivery log, disk-full alert threshold (email admins at 90% of `/shared`) |

Admins are web-only too; host-level operations that aren't in the panel stay
with sysadmin accounts as today.

---

## 8. Email

- Same transactional mail as today via the existing Resend path (outbound
  internet is available) with SMTP as an alternative; the API key lives only
  in the `worker`/`web` environment from a secrets file, never in the repo or
  DB.
- Emails: set-password, reset-password, application received (to admins),
  application approved/rejected, sign-in lockout, session-ending warning,
  extension confirmation, notify-when-free, disk-full (admins), job
  BEGIN/END/FAIL (existing `slurm-deck-mailer`, kept).
- **All user-controlled values are HTML-escaped** in every template (today's
  `slurm-deck-mailer` inserts job names unescaped).
- Times shown in the configured timezone with the correct label (today's
  emails hardcode "GMT+5:30").
- An outbox table with retries so a slow mail provider never blocks a request.

---

## 9. Deployment

### 9.1 Recommended layout (answer to "run it in a container or suggest the best way")

- **Docker Compose on the login node** for `caddy`, `web`, `worker`, `db`,
  installed and managed by slurmadmin, containers running as `sdweb`
  (`worker` as `sdworker`).
- **deck-agent** as a systemd service on the login node, plus the GPU-host
  helper script reached over restricted SSH (§4.2 explains why).
- **Slurm, munge, NFS, GPU, slurmd, slurmctld, slurmdbd stay exactly where they
  are, not containerised.** They work; containerising them adds risk for no
  benefit.

`web`/`worker` containers mount only the secrets file and deck-agent's Unix
socket. No `/shared`, no munge key, no `/etc/shadow`, no Docker socket.

### 9.2 Install and upgrade
- An installer step (extend the existing `install-wizard.sh` / `deploy/wizard`)
  that, run as slurmadmin on the login node: resizes nothing itself but checks
  the login node meets the §4.1 sizing, creates `sdweb` and `sdworker`, installs the Compose
  stack, deck-agent, the GPU-host helper and its SSH key, writes `site.env`
  (hostname, allow-list seed, timezone, cluster name, mail), creates the first admin account
  (prints a one-time set-password link), sets up the GPU-host port forward,
  avahi name and firewall rules.
- `docker compose pull && up -d` for upgrades; DB migrations run on start.
- Backups: nightly `pg_dump` run by slurmadmin to
  `/var/backups/slurm-deck/` on the login node (slurmadmin-only), 14 kept,
  optionally copied to an admin-only folder on `/shared`.

### 9.3 Settings (all in `site.env` or the admin panel; nothing hardcoded)
`PUBLIC_HOSTNAME`, `GPU_HOST_ADDR`, `LOGIN_NODE_ADDR`,
`NFS_ROOT`, `SLURM_PARTITION`, `COMPUTE_NODE_NAME`, `CLUSTER_NAME`,
`CLUSTER_TZ`, `MAIL_FROM`, mail provider settings, `ALLOWLIST_SEED`,
`NOTEBOOK_PORT_RANGE`. Admin-panel settings live in the DB.

---

## 10. Security changes bundled with this

These come from the 2026-10-23 audit and must land with the web platform (or
before it), because the web model depends on them:

1. Normal/admin users **lose login-node accounts**; sshd on the login node only
   admits shell users and sysadmins (`AllowGroups`). The ForceCommand gateway
   wrapper is retired.
2. **Remove the `docker` group** from every account except sysadmins on both
   nodes — web users **and shell users** (decided: "lose Docker, only
   Apptainer"). This reverts commit 63b8cc6. Containers in jobs are Apptainer
   only; `slurm-deck-adduser` stops adding `docker` (it is root-equivalent).
3. `/shared/envs`, `/shared/models`, `/shared/datasets`, `/shared/scripts`,
   `/shared/templates` become **admin-write, user-read** (today every
   `gpuusers` member can modify them — cross-user code execution).
4. All shared mutable JSON files (env/model registries, templates, pod-notify
   subscriptions) move into the DB with per-user ownership.
5. Notebook/TensorBoard/terminal ports firewalled to the login node only; the
   login node's `PermitOpen 192.168.122.1:*` goes away with ForceCommand.
6. UID allocation via a monotonic counter (§5.2).
7. Strict username validation in every account-removal path.
8. Services stop running as named people's accounts (`User=dahamadmin`,
   `User=root-daham` in the pod-notify and stats units) — dedicated service
   accounts instead.

Out of scope here but noted: `ConstrainDevices` is already on (good); GPU
memory is still not partitioned between jobs sharing the card — the 17
CUDA-OOM failures. **[builder's call / follow-up]** evaluate CUDA MPS with
`CUDA_MPS_PINNED_DEVICE_MEM_LIMIT` to enforce per-job VRAM; at minimum show
live free VRAM on the review step and set
`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` in job scripts.

---

## 11. Branches and where work comes from (decided)

- **`legacy/v1.4-tui`**: the whole v1.4 TUI codebase with its history. The
  live cluster deploys from it (`/opt/slurm-deck`) until cutover. It only gets
  critical fixes to the running TUI (e.g. the gateway bypass and docker-group
  fixes from the 2026-10-23 audit), never web work.
- **`dev`**: the integration branch for the web platform. It started clean
  (this design, `CLAUDE.md`, README, LICENSE).
- **`main`**: the release branch. It changes only when `dev` is merged into it
  at a release point, by pull request. It no longer feeds the live TUI.
- **Work comes from SerenEdge.** Every change is a SerenEdge task or issue with
  a key, built on `task/<KEY>-<short-slug>` or `issue/<KEY>-<short-slug>` off
  `dev`, merged back by pull request, with commit messages `<KEY>: summary` and
  no AI/agent attribution. `CLAUDE.md` holds the full rules.
- Implementation plans for the web platform go in `docs/plans/` on `dev`.

---

## 12. Cutover (decided: start fresh, keep folders)

1. Build and test the web platform alongside the TUI, with test accounts. The
   web platform is installed from a `main` release into `/opt/slurm-deck-web`
   and reached on 443; the TUI keeps running from `legacy/v1.4-tui` in
   `/opt/slurm-deck` over SSH on 2225. Both share the same Slurm and `/shared`.
2. Announce a cutover date (maintenance banner + email to current users).
3. At cutover: disable ForceCommand logins; **delete the login-node accounts
   of all normal users and admins** (not shell users, not sysadmins); keep
   every `/shared/users/<name>` and `/shared/jobs/<name>` folder.
4. Admins create web accounts (or approve applications) for people who should
   continue, **reconnecting their old folders** (§5.5). Each person sets a new
   password from the emailed link.
5. Old job history is **not** imported into the dashboard; old job folders
   remain on disk for admins.
6. Folders of people who never return stay put until an admin archives them.
7. After a settling period, retire the TUI: remove `/opt/slurm-deck`, the
   ForceCommand drop-in, the gateway wrapper and the old audit daemon.
8. Rollback (before step 7): re-enable ForceCommand and restore the removed accounts from a
   pre-cutover `/etc/passwd`/`/etc/shadow`/`/etc/group` backup on both nodes
   (taken in step 3).

---

## 13. Practical use cases (acceptance scenarios)

1. **New student, notebook.** Admin approves Amaya's application → she sets a
   password → New job → Notebook, data-science env, 1 pod, 8 h → card goes
   Queued → Starting → Ready → Open → JupyterLab in a new tab in her own
   folder, no token. She deletes a scratch file — it works (no `.Trash` 500).
2. **150 GB dataset.** Menura uploads `imagenet_subset.tar` (150 GB) on wired
   LAN; closes his laptop at 60%; reopens next morning and it resumes; it
   finishes in ~25 min of transfer; he clicks Extract; it lands in
   `datasets/imagenet_subset/`.
3. **Fine-tune that runs long.** Yenuli's 8 h QLoRA run gets the 30-minute
   warning email; she clicks Extend +4 h from the email → job page → allowed
   (12 h ≤ 24 h cap) → new limit shown. Later she tries another +16 h → refused
   with the reason.
4. **Host OOM.** A job is killed by `oom_kill`; the job page shows "Out of
   memory: the job used more than its 15 GB RAM" (parsed from the `.err`) and
   suggests taking 2 pods.
5. **Parameter sweep.** Hassan submits a script with a job array `0-19%4` and
   a dependency on a preprocessing job; history shows each array task.
6. **TensorBoard.** Dinugi starts TensorBoard on `runs/`; only she (and admins)
   can open it; another student pasting her URL gets "not your session".
7. **Build an env.** Sanuth builds `myenv` from a `requirements.txt` including
   `tensorboard`; the build runs as a Slurm CPU job; the log streams; the
   package check confirms everything installed before the env is listed.
8. **Gated model.** Indrajith downloads `meta-llama/...` with his HF token; it
   runs as a Slurm job, resumable, into his area.
9. **GPU full.** Janeesha sees 4/4 pods busy, subscribes to "notify me at 2
   free pods", gets one email when it happens.
10. **Admin approves an outsider.** An industry partner applies from
    `partner@company.com` (on the allow-list as a single address) → admin
    approves as user. A friend applying from gmail.com is refused at the form.
11. **Returning user.** Admin creates `amasha`; the panel finds her 142 GB
    folder; admin confirms; she signs in and her `PlurVa/` project is there.
12. **Maintenance.** Admin sets a banner, drains the node with "cancel running
    jobs", resizes pods 4 → 2, resumes; every step is in the audit log.
13. **Shell user untouched.** A shell user SSHes to the login node and runs
    `sbatch` and `rsync` exactly as before.
14. **Account removed.** Admin deletes `team-physionet`: jobs cancelled, hidden
    accounts and Slurm association gone, folder renamed `.offboarded`, the
    UID is never handed to anyone else.

---

## 14. Testing

- **Unit:** auth (hashing, lockout, reset tokens, session sliding/absolute
  expiry boundaries), allow-list matching, application flow, cap math,
  UID allocator, sbatch rendering (reuse existing tests), path jails.
- **deck-agent:** each verb drops privileges correctly (runs a real fork as a test
  uid), rejects paths outside the user's roots, rejects malformed payloads
  without dying, a slow request does not block a fast one, extend checks.
- **API:** FastAPI TestClient for every endpoint, including authorization
  (user A cannot touch user B's jobs/files/notebooks; non-admin cannot reach
  admin endpoints).
- **Proxy:** notebook/TensorBoard proxy refuses non-owners on HTTP and on
  WebSocket upgrade.
- **Uploads:** resume after interruption, multi-GB file with a small memory
  ceiling on the container, free-space refusal.
- **End-to-end:** the §13 scenarios against demo mode first, then a test
  account on the real cluster (this project's standing practice).
- CI runs on Linux (the suite already needs `grp`/`fcntl`); shell scripts
  checked out with LF endings.

---

## 15. What's left to the builder

- Frontend framework and component library (constraint: the §6 visual rules,
  no CDN fonts, works offline on the LAN).
- Terminal-server choice for terminal sessions.
- Reusing `slurm-deck-adduser` logic vs. porting provisioning into
  deck-agent.
- Exact DB schema and migration tool.
- Chunk size and tus server library.
- How the TUI code is retired: shell users may keep running `slurm-deck`
  manually if useful; it is no longer anyone's forced entry point.
- Implementation order — suggested: deck-agent + identity + auth → files/uploads →
  jobs/New job → notebooks proxy → environments/models → admin panel →
  cutover tooling.

## 16. Open risks

- **deck-agent and the GPU-host helper are the highest-risk components**
  (root, switch users). They need their own focused security review before
  deployment.
- **The login node does more now** (Slurm control plane + all file traffic).
  If it goes down, the web platform can't reach jobs or files either; size it
  up (§4.1) and watch its load.
- **mDNS** may not resolve on some managed Windows machines; the fallback is a
  LAN DNS record or a hosts-file entry.
- **Internal CA** requires each user to trust a certificate once; the sign-in
  page must make that easy.
- **Upload throughput** (browser → login node → NFS → NVMe) is
  unproven; measure early.
- **Admins lose shell-free power tools** (e.g. "Log in as user" becomes View as
  user); anything not in the panel needs a sysadmin.
