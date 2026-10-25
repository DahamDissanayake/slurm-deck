# Security review of the privileged components (2026-10-25)

This is the spec §16 review (SLURM-49) of deck-agent, the GPU-host helper, the
session proxy and web sign-in, done before the platform is installed for real
users. It covers `origin/dev` at `a3ef794`:

- `src/deckagent/**`, `gpuhost/sd-gpu-helper` and `deploy/systemd/deck-agent.service`
- `src/sdweb/proxy/**` and `src/sdweb/auth/**`
- the installer's `sdprov` key and sudoers, `deploy/Caddyfile` and `deploy/compose.yaml`

It was checked against spec §4.3 (deck-agent), §5.3 (authentication), §6.4
(sessions) and §10 (security changes).

A follow-up pass (SLURM-71) closed the gaps the first pass left:
- the two verb files it had only skimmed;
- the §10 hardening scripts in `deploy/cluster/harden/`;
- read-only checks on the live cluster on 2026-10-25, recording metadata only
  (modes, ACLs, group members, services, Slurm version), never file contents;
- proof tests for the two high findings.

That pass added findings 13 to 15.

Each finding has an issue task. The platform should not go to real users while
a high-severity finding is still open.

| # | Severity | Finding | Issue |
|---|----------|---------|-------|
| 1 | High | Session content runs on the platform's own origin | SLURM-56 |
| 2 | High | `env.check_imports` runs user-controlled code on the login node | SLURM-57 |
| 3 | Medium | `admin.publish_shared` checks the source path as text only | SLURM-58 |
| 4 | Medium | GPU-host helper acts on any account with a UID of 1000 or more, not only web accounts | SLURM-59 |
| 5 | Medium | Admin role comes from database rows alone | SLURM-60 |
| 6 | Low | `scontrol --oneliner` parsing can be spoofed | SLURM-61 |
| 7 | Low | Upload chunks have no actor in the deck-agent audit log | SLURM-62 |
| 8 | Low | Proxy WebSockets: no Origin check, not closed on sign-out | SLURM-63 |
| 9 | Low | Upload grants outlive logout and account disable | SLURM-64 |
| 10 | Low | deck-agent systemd unit is lightly hardened | SLURM-65 |
| 11 | Info | Postgres is reachable on the login node's loopback | SLURM-66 |
| 12 | Info | `fs.extract` has no cap on total size | SLURM-67 |
| 13 | Medium | No install or cutover step runs the §10 hardening scripts | SLURM-68 |
| 14 | Medium | `shared-areas.sh` misses folders and default ACLs | SLURM-69 |
| 15 | Medium | Named-person ACLs on every user folder and shared area | SLURM-70 |

## Findings

### 1. Session content runs on the platform's own origin (High, SLURM-56)

`src/sdweb/proxy/routes.py:236-240`. `/notebook/`, `/tensorboard/` and
`/terminal/` are served from the same origin as the app, and the job's owner
controls what the session port serves. When an admin opens a user's session,
that page's JavaScript can read the CSRF token from `GET /api/auth/me` and call
any admin API as the admin. Upstream `Set-Cookie` (which can overwrite
`sd_session`), `Service-Worker-Allowed` and `Clear-Site-Data` headers also pass
through unfiltered.

**Proof:** `tests/web/test_proxy.py::test_job_cannot_set_platform_cookie_or_service_worker_scope`.
The test job returns `Set-Cookie: sd_session=attacker-token`, and that header
reaches the admin's browser. The test is marked strict xfail, so it passes CI
while the bug exists and fails once SLURM-56 fixes it, which forces the marker
to be removed.

**Fix:** serve sessions from a separate origin. Until then, drop those headers.

### 2. `env.check_imports` runs user-controlled code on the login node (High, SLURM-57)

`src/deckagent/verbs/envs.py:113-115`. The verb runs `<env_path>/bin/python` as
the user, and `env_path` may be the user's own env. Two things in that folder
can run any code the user wants:

- the `python` file itself;
- a `.pth` file in its site-packages, because `-I` does not turn off `site`.

A process that daemonizes outlives the 20 s timeout. This breaks the §10 rule
that web users have no login-node access.

**Proof:** `tests/agent/test_verbs_envs.py::test_check_imports_never_runs_the_users_interpreter`.
A user env whose `bin/python` creates a marker file is passed to the verb, and
the marker appears. The test is marked strict xfail, the same way as finding 1.

**Fix:** never run the env's interpreter. Read its site-packages as files instead.

### 3. `admin.publish_shared` checks the source path as text only (Medium, SLURM-58)

`src/deckagent/verbs/admin.py:389-393`. The check uses `normpath`, not
`realpath`. If a folder along a user's path is a symlink to another user's
folder, `cp -a` running as sd-ops copies that user's data into a shared area
everyone can read.

**Live check:** every `/shared/users/<u>` folder grants `group:gpuadmins:rwx`,
and sd-ops does its file work through that group. So sd-ops can read every
user's folder, which is what makes this attack possible.

**Fix:** resolve the path as sd-ops and require the result to stay under
`users/<owner>/`.

### 4. The helper acts on any account with a UID of 1000 or more (Medium, SLURM-59)

`gpuhost/sd-gpu-helper:180-257`. `delete-account`, `purge` and `archive` work on
sysadmin and shell accounts, not only web accounts. `create-account` on an
existing account runs `passwd -l` and `chown -R` on its home. So whoever
controls the login node can lock sysadmins out and wipe any user's folders on
the NFS server.

**Fix:** require webusers membership, and no privileged group, before any
mutating command.

### 5. Admin role comes from database rows alone (Medium, SLURM-60)

`src/deckagent/sessions.py:106-122`. A forged or edited session row with
`role=admin` gets admin powers, including `as_ops` jobs that run as sd-ops.
sd-ops can write the shared envs, so this reaches code execution as every
user. Spec §4.3 accepts this risk only for normal web users.

**Fix:** require a second check outside the database, or sign session rows.

### 6. `scontrol --oneliner` parsing can be spoofed (Low, SLURM-61)

`src/deckagent/verbs/jobs.py:136-155`. A user-controlled value can add a fake
key. For example, a WorkDir containing ` UserId=alice(…)` replaces the real
owner. This was confirmed with the module's own regex. The impact is limited to
the user's own jobs.

**Live check:** the cluster runs Slurm 25.11.2, and `scontrol show job --json`
works there. No job was running, so the real field order of `--oneliner`
couldn't be confirmed live.

**Fix:** read job fields from structured output (`--json` or fixed formats).

### 7. Upload chunks have no actor in the audit log (Low, SLURM-62)

`src/deckagent/server.py:238-239`. `fs.write_chunk` is authorised by a grant,
not a session, and its audit line records actor `null`.

### 8. Proxy WebSockets (Low, SLURM-63)

`src/sdweb/proxy/routes.py:263-296`. The WebSocket handler has no Origin check
and relies on SameSite=Strict alone. An open socket also stays open after
logout or account disable.

### 9. Upload grants outlive logout and disable (Low, SLURM-64)

A grant stays valid for 6 h whatever happens to the session or account.

### 10. deck-agent unit hardening (Low, SLURM-65)

The unit has no `CapabilityBoundingSet`, `ProtectSystem=strict`,
`ProtectKernel*`, `RestrictNamespaces` or `UMask=0077`.

### 11. Postgres on the login node's loopback (Info, SLURM-66)

`deploy/compose.yaml:45` publishes Postgres on `127.0.0.1:5432`. Shell users,
who still have login-node accounts, can reach it. A password is still required.
The platform isn't installed yet, so this couldn't be checked live. The login
node has 20 accounts with a UID of 1000 or more, so the exposure would be real.

### 12. `fs.extract` has no size cap (Info, SLURM-67)

A zip bomb can fill `/shared` for everyone.

### 13. No install or cutover step runs the §10 hardening scripts (Medium, SLURM-68)

`deploy/cluster/harden/` holds the scripts for §10 items 2, 3 and 8:
`remove-docker-group.sh`, `shared-areas.sh` and `service-accounts.sh`. But no
installer step, `cutover.sh` or runbook runs them. Live on 2026-10-25, none of
§10 had been applied:

- the `docker` group (root-equivalent) has 16 to 17 members on each node;
- a normal user (`tuser`) can write `/shared/envs`;
- `sd-ops` and `sd-stats` don't exist;
- `slurm-deck-stats` runs as `root-daham`.

**Fix:** make the installer or cutover run each script, `--check` then
`--apply`, and refuse to finish until it has.

### 14. `shared-areas.sh` misses folders and default ACLs (Medium, SLURM-69)

The script resets owners, modes and access ACLs, but leaves
`default:other::rwx` on `envs`, `models`, `data` and `templates`. Files created
there later are world-writable.

It also skips four folders:

| Folder | Why it matters |
|---|---|
| `/shared/templates` | Every `gpuusers` member can write it today, and §10.3 names it |
| `/shared/miniforge3` | Every job script sources its `conda.sh` (`sdcore/sbatch.py`). Today only `root-daham`'s group can write it, but nothing keeps it that way |
| `/shared/training-scripts` | Not managed at all |
| `/shared/tmp` | Not managed at all |

**Fix:** add those folders, reset the default ACLs, and report both in `--check`.

### 15. Named-person ACLs on every user folder and shared area (Medium, SLURM-70)

Every `/shared/users/<u>` folder and every shared area carries
`user:iit:rwx` and `user:daham:rwx`, as both access and default entries.
`daham` is in `gpuusers`, not `gpuadmins`. If `daham` becomes a web account,
deck-agent acting as `daham` can read and write every user's folder. That
removes the per-user kernel boundary §4.3 relies on, and it goes against §10.8.

**Fix:** remove named-user ACL entries, keeping each folder owner's own, and
give admin access only through `gpuadmins` and sd-ops. Confirm with the Head
first.

## How the review was done

- **Code:** the files in scope were read in full and traced by hand against
  the spec sections above. The original pass only skimmed
  `verbs/cluster.py` and `verbs/usage.py`; the follow-up read them in full.
- **Tests:** the attack types the task lists are also covered by existing
  tests, which pass in `serenedge ci`:
  - malformed requests and slow clients: `tests/agent/test_server.py`;
  - path traversal: `tests/agent/test_fsops.py` and `test_verbs_files.py`.
- **Proof tests:** findings 1 and 2 each have one, and finding 6 was
  reproduced with the module's own regex.
- **Live cluster:** read-only metadata checks on the GPU host and the login
  node on 2026-10-25. Nothing was changed and no file contents were read.

**Limits:** no finding was exploited on the live system, the platform wasn't
installed so its runtime couldn't be checked, and there was no fuzzing or load
testing. The front-end, the worker and API routes outside proxy and auth were
out of scope.

## Checked with no finding

- **Option injection into fsops:** paths always follow `--`.
- **Path traversal in every fs verb:** paths are resolved with `realpath` and
  jailed, then the work runs as the user, so the kernel enforces permissions too.
- **Archives:** members that climb out of the folder, links and special files
  are all refused before anything is written.
- **Slow clients:** the request deadline is re-checked before every read, so a
  trickle gets 408.
- **Malformed requests:** oversize JSON (413), bad request lines and headers,
  and chunked bodies (411) are all refused cleanly.
- **View-as abuse:** the target must be an active, non-admin web account. An
  admin who is viewing as a user is refused admin verbs, `as_ops` and
  `as_admin`.
- **Worker role:** limited to the cluster-wide read-only verbs.
- **`verbs/cluster.py` and `verbs/usage.py`:** queue job names are shown only
  to the job's owner and admins, cluster-wide usage is admin-only (and refused
  while viewing as a user), and `du` runs as sd-ops.
- **GPU stats file:** deck-agent reads `/shared/.gpu_stats.json` as root.
  Checked live: users can't replace it, because `/shared` itself is writable
  only by its owner and `gpuadmins`.
- **§10 items 1, 5, 6 and 7:** these are in place in code:
  - `AllowGroups` and the ForceCommand removal in `cutover.sh`;
  - the session-port firewall in `sd-session-ports.nft`;
  - UIDs from the `web_uid_seq` Postgres sequence, which never wraps around
    (`NO CYCLE`; used by `accounts/service.py` and `cli.py`);
  - strict username checks in `account.delete` and the helper.

  Neither the cutover nor the firewall has been applied live yet.
- **Helper parsing:** no shell, an exact argument count per command, sudoers
  that allows no arguments, and an SSH key restricted to the forced command.
- **Upload grants:** the HMAC is checked with `compare_digest`, so grants can't
  be forged.
- **Proxy SSRF:** the target must be the job's own node and a port in the
  session range, and the Host header is pinned.
- **Request header leakage:** `sd_session`, the CSRF header, `Authorization`
  and `X-SD-Token` are stripped before forwarding.
- **Sign-in:** an unknown email costs the same time as a wrong password, reset
  links are single-use and stored hashed, and lockout and per-IP limits follow
  §5.3. Uvicorn trusts forwarded headers, but only Caddy can reach port 8000.
