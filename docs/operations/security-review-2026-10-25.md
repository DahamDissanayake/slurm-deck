# Security review of the privileged components (2026-10-25)

This is the spec §16 review (SLURM-49) of deck-agent, the GPU-host helper, the
session proxy and web sign-in, done before the platform is installed for real
users. It covers `origin/dev` at `a3ef794`:

- `src/deckagent/**`, `gpuhost/sd-gpu-helper` and `deploy/systemd/deck-agent.service`
- `src/sdweb/proxy/**` and `src/sdweb/auth/**`
- the installer's `sdprov` key and sudoers, `deploy/Caddyfile` and `deploy/compose.yaml`

It was checked against spec §4.3 (deck-agent), §5.3 (authentication), §6.4
(sessions) and §10 (security changes).

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

## Findings

### 1. Session content runs on the platform's own origin (High, SLURM-56)

`src/sdweb/proxy/routes.py:236-240`. `/notebook/`, `/tensorboard/` and
`/terminal/` are served from the same origin as the app, and the job's owner
controls what the session port serves. When an admin opens a user's session,
that page's JavaScript can read the CSRF token from `GET /api/auth/me` and call
any admin API as the admin. Upstream `Set-Cookie` (which can overwrite
`sd_session`), `Service-Worker-Allowed` and `Clear-Site-Data` headers also pass
through unfiltered.

**Fix:** serve sessions from a separate origin. Until then, drop those headers.

### 2. `env.check_imports` runs user-controlled code on the login node (High, SLURM-57)

`src/deckagent/verbs/envs.py:113-115`. The verb runs `<env_path>/bin/python` as
the user, and `env_path` may be the user's own env. Two things in that folder
can run any code the user wants:

- the `python` file itself;
- a `.pth` file in its site-packages, because `-I` does not turn off `site`.

A process that daemonizes outlives the 20 s timeout. This breaks the §10 rule
that web users have no login-node access.

**Fix:** never run the env's interpreter. Read its site-packages as files instead.

### 3. `admin.publish_shared` checks the source path as text only (Medium, SLURM-58)

`src/deckagent/verbs/admin.py:389-393`. The check uses `normpath`, not
`realpath`. If a folder along a user's path is a symlink to another user's
folder, `cp -a` running as sd-ops copies that user's data into a shared area
everyone can read.

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

### 12. `fs.extract` has no size cap (Info, SLURM-67)

A zip bomb can fill `/shared` for everyone.

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
