# Phase 7 — Installer, Hardening and Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A repeatable installer that puts the whole platform on the login node, the cluster-side hardening the web model depends on, backups, a scripted acceptance run of the spec's 14 scenarios, and cutover + rollback tooling that retires the TUI without losing anyone's folders.

**Architecture:** One idempotent Python (stdlib) installer run by slurmadmin with `sudo`, recording progress in a state file so it can resume, reaching the GPU host once through an admin SSH login (`root-daham` today; any sudo account) to install the helper and its narrow `sdprov` access, after which only the helper is used. Hardening and cutover are separate scripts with a `--check` mode that changes nothing, so each change is reviewed before it's applied.

**Tech Stack:** Python ≥ 3.11 stdlib, bash, systemd, nftables, avahi.

**Spec:** §4.1 (network, name, HTTPS, sizing), §9, §10, §12, §13, §16. **Roadmap:** shared names, paths.

## Global Constraints

- Roadmap constraints apply.
- Every script that changes cluster state has `--check` (print planned changes, exit 0, change nothing) and refuses to run without `--apply`.
- The legacy TUI keeps working at every step until cutover step "disable ForceCommand".
- Nothing deletes anything under `/shared/users` or `/shared/jobs`.
- Site values come only from `/etc/slurm-deck-web/site.env` written by the installer; scripts never embed IPs or hostnames.

## Review Focus

- **Installer interrupted halfway** — rerun resumes from the state file and does not duplicate accounts, keys or firewall rules. Test in Task 1.
- **Removing the docker group from someone who has a running container** — the script lists running containers per user in `--check` and doesn't stop them; it only removes the group. Test in Task 3.
- **Cutover finds a user who is both a shell user and in gpuusers** — classified as shell user and left untouched, flagged for the admin. Test in Task 6.
- **Rollback after some web accounts already reused old UIDs** — rollback restores login-node accounts without clashing; it refuses (and lists the clashes) instead of overwriting. Test in Task 6.
- **mDNS not resolving on a client** — sign-in page and runbook give the hosts-file line `10.35.4.100 slurmdeck.local` (from site values). Test in Task 2.

---

### Task 1: Installer

**Files:**
- Create: `deploy/installer/__main__.py`, `deploy/installer/steps.py`, `deploy/installer/state.py`, `deploy/installer/templates/` (`agent.env.tmpl`, `web.env.tmpl`, `secrets.env.tmpl`, `site.env.tmpl`, `gpu-helper.env.tmpl`), `install.sh` (thin wrapper: `exec sudo python3 -m deploy.installer "$@"`), `tests/installer/test_steps.py`
- Source: `legacy/v1.4-tui:deploy/wizard/` (prompt/target patterns, `ssh_target.py`).

**Interfaces:**
- Produces: `python3 -m deploy.installer [--check] [--resume] [--answers answers.json]`. Steps, each idempotent with a `done` flag in `/etc/slurm-deck-web/install-state.json`:
  1. `preflight` — login node ≥ 4 vCPU and ≥ 12 GB RAM and swap present (warn and require `--accept-small` otherwise); `sinfo`, `munge -n | unmunge` work; `/shared` mounted and matches `NFS_ROOT`; Docker + Compose v2 present; Python ≥ 3.11.
  2. `site_values` — prompt or read: public hostname, GPU host address on virbr0, login node address, LAN address, NFS root, partition, compute node name, cluster name, timezone, mail provider + from, allow-list seed (may be empty), first admin email/name/username.
  3. `accounts_login` — create `sdweb`, `sdworker` (system, nologin), `sd-ops` (nologin, fixed UID chosen free on both nodes, in `gpuadmins`), group `webusers`.
  4. `gpuhost_bootstrap` — via the admin SSH login: create `sd-ops` (same UID), `webusers`, `sdprov`; install `sd-gpu-helper`, `gpu-helper.env`, `sudoers-sdprov` (validated with `visudo -cf`); generate an ed25519 key on the login node (`/etc/slurm-deck-web/gpuhost_ed25519`, root 0600) and install its public half in `sdprov`'s `authorized_keys` with the forced command; verify `ping` through the helper.
  5. `slurm_assoc` — `sacctmgr -i add user sd-ops account=default qos=normal`.
  6. `secrets` — 32-byte grant key, Fernet key (if approved), Postgres passwords for app and `sd_agent_ro`, written to the env files with the modes in the roadmap.
  7. `agent` — venv at `/opt/slurm-deck-web/agent-venv` with `.[agent]`, `deck-agent.service`, start, health check (`cluster.disk_free` as a fake worker via a one-shot `sdworker` uid call).
  8. `web_stack` — `docker compose build && up -d`, `migrate`, `create-admin` (prints the set-password link).
  9. `network` — Task 2 scripts with `--apply`.
  10. `summary` — prints URL, CA certificate download path, hosts-file fallback line, and the cutover runbook path.

- [ ] **Step 1:** Tests run steps against a fake `Target` (records commands): rerun after a failure in step 4 skips 1–3; `--check` produces commands but executes none; templates never contain an empty required value; secrets file modes 0640/0600 as specified.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add resumable installer for the login node and GPU-host bootstrap`.

---

### Task 2: Network — port forward, mDNS name, session-port firewall

**Files:**
- Create: `deploy/cluster/gpuhost/sd-web-forward.sh`, `deploy/cluster/gpuhost/sd-mdns-alias.service`, `deploy/cluster/gpuhost/sd-session-ports.nft`, `tests/installer/test_network.py`

**Interfaces:**
- Produces:
  - `sd-web-forward.sh --check|--apply|--remove` on the GPU host: DNAT TCP 443 and 80 on the LAN address to the login node, mirroring how the existing 2225 → 22 forward is implemented (the script first detects the mechanism — libvirt qemu hook, nftables or iptables — prints it in `--check`, and uses the same one; aborts with a message if it finds none).
  - `sd-mdns-alias.service`: `ExecStart=/usr/bin/avahi-publish -a -R ${PUBLIC_HOSTNAME} ${LAN_ADDR}` with `EnvironmentFile=/etc/slurm-deck-web/gpu-helper.env`; `Restart=always`.
  - `sd-session-ports.nft`: table `inet sd_sessions` accepting TCP `SESSION_PORT_RANGE` on the compute node's virbr0 address only from the login node address, dropping it from everywhere else (LAN included).
  - Sign-in page hint (Phase 2 page) gets a "Can't reach slurmdeck.local?" disclosure with the hosts-file line built from `SD_PUBLIC_HOSTNAME` and the LAN address (new web setting `SD_LAN_ADDR`).

- [ ] **Step 1:** Tests: `--check` on a fake host with an nftables 2225 rule prints the nftables plan; with no forward found it exits 2 with "Couldn't find how port 2225 is forwarded; set up the 443 forward by hand."; the nft file parses with `nft -c -f` (skipped when nft missing).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add web port forward, mDNS alias and session-port firewall`.

---

### Task 3: Cluster hardening scripts

**Files:**
- Create: `deploy/cluster/harden/remove-docker-group.sh`, `deploy/cluster/harden/shared-areas.sh`, `deploy/cluster/harden/service-accounts.sh`, `deploy/cluster/sd-stats-writer` + `deploy/systemd/sd-stats-writer.service`, `deploy/cluster/slurm-deck-mailer`, `tests/installer/test_harden.py`
- Source: `legacy/v1.4-tui:deploy/slurm-deck-stats-writer`, `deploy/slurm-deck-stats.service`, `deploy/slurm-deck-mailer`, `deploy/check-shared-perms.sh`, `deploy/fix-shared-perms.sh`.

**Interfaces:**
- Produces:
  - `remove-docker-group.sh --check|--apply [--keep user,...]` (run on each node): removes every member of `docker` except the sysadmin list from site values (`SYSADMINS`, e.g. `root-daham,iit,slurmadmin`); `--check` lists members and their running containers.
  - `shared-areas.sh --check|--apply`: `/shared/{envs,models,datasets,data,images,scripts}` → owner `sd-ops:gpuadmins`, dirs 2775, files 0664→0644 for others' write bits removed, default ACL `g:gpuadmins:rwx`, removes `g:gpuusers:rwX` write ACLs; never touches `users/` or `jobs/`; `--check` prints counts of paths that would change.
  - `service-accounts.sh --check|--apply`: creates `sd-stats` on the GPU host; the stats writer (ported, `NFS_ROOT` from env, writes `$NFS_ROOT/.gpu_stats.json` 0644) runs as `sd-stats` instead of `root-daham`; the legacy pod-notify timer (`User=dahamadmin`) is disabled (replaced by the worker).
  - `slurm-deck-mailer` ported with every value `html.escape`d and the timezone label from site values; `MailProg` keeps pointing at `/usr/local/bin/slurm-deck-mailer`.

- [ ] **Step 1:** Tests: `remove-docker-group.sh --check` with a fake `getent`/`docker ps` lists users and containers and changes nothing; `--keep` honoured; `shared-areas.sh --check` never lists a path under `users/` or `jobs/`; mailer escapes `<b>` in a job name.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add docker-group removal, shared-area permissions and service-account scripts`.

---

### Task 4: Backups

**Files:**
- Create: `deploy/systemd/sd-backup.service`, `deploy/systemd/sd-backup.timer`, `deploy/cluster/sd-backup.sh`, `docs/operations/restore.md`, `tests/installer/test_backup.py`

**Interfaces:**
- Produces: nightly 02:30 (cluster timezone) `docker compose exec -T db pg_dump -Fc` as slurmadmin into `/var/backups/slurm-deck/sd-<YYYYmmdd>.dump` (0600 slurmadmin), keep 14 (`BACKUP_KEEP`), plus a copy of `/etc/slurm-deck-web/*.env` (0600) and the agent audit log; optional copy to `$NFS_ROOT/.admin-backups/` when `BACKUP_COPY_TO_SHARED=1`. `restore.md` gives the exact restore commands.

- [ ] **Step 1:** Test: pruning keeps the 14 newest of 20 fake dumps.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add nightly database and config backups`.

---

### Task 5: Acceptance run (spec §13)

**Files:**
- Create: `tests/e2e/conftest.py`, `tests/e2e/test_scenarios.py`, `docs/operations/acceptance-checklist.md`

**Interfaces:**
- Produces: `SD_E2E=1 SD_E2E_URL=https://slurmdeck.local pytest tests/e2e` against a real test install using two throwaway web accounts and one admin (created and deleted by the fixture). Automated (API level) scenarios: 1 (notebook ready + proxied `/api/status` 200), 2 (20 GB stand-in upload resumed after an interrupted PATCH), 3 (extend allowed then refused past cap), 4 (OOM job explanation; job allocates more RAM than its pods), 5 (array `0-3%2` + dependency), 6 (TensorBoard 403 for the other user), 7 (env build with `tensorboard` verified), 9 (notify consumed once), 10 (allow-listed address applies; gmail refused), 11 (reconnect keeps folder contents), 12 (drain/resume + audit rows), 14 (delete archives folder; next new account gets a different UID). Manual, in the checklist: 8 (gated model with a real token), 13 (shell user SSH + `sbatch` + `rsync` unchanged), plus browser checks (no certificate warning after trusting the CA, dark/light, new-tab opening).

- [ ] **Step 1:** Write the scenario tests and checklist.
- [ ] **Step 2:** Run against the test install → every automated scenario PASS; record the run and the manual checklist results in the PR.
- [ ] **Step 3:** Commit `<KEY>: add acceptance scenarios and manual checklist`.

---

### Task 6: Cutover and rollback tooling

**Files:**
- Create: `deploy/cutover/snapshot.sh`, `deploy/cutover/classify.py`, `deploy/cutover/cutover.sh`, `deploy/cutover/rollback.sh`, `deploy/cutover/retire-tui.sh`, `docs/operations/cutover-runbook.md`, `tests/installer/test_cutover.py`

**Interfaces:**
- Produces:
  - `snapshot.sh` (both nodes): copies `/etc/{passwd,shadow,group,gshadow}` and `/etc/ssh/sshd_config.d/` to `/var/backups/slurm-deck/cutover-<ts>/<node>/` (0600 root), plus `sacctmgr dump`.
  - `classify.py <snapshot dir>` → `cutover-plan.json`: `{"remove": [user...], "shell": [...], "sysadmin": [...], "service": [...], "flagged": [{user, reason}]}`. Remove = in `gpuusers` (or `gpuadmins`), uid ≥ 1000, not in the site's `SYSADMINS`, not a shell user. Shell user = not in `gpuusers`, real shell, uid ≥ 1000. Anyone matching both → `flagged`, never removed.
  - `cutover.sh --check|--apply <plan>`: (1) web maintenance banner + email to the old users' addresses exported from the legacy `users.db` (`--announce` sub-step, run days earlier); (2) disable the ForceCommand drop-in and set `AllowGroups <shell group> <sysadmin group>` (installer creates group `shellusers` holding the plan's `shell` list), `sshd -t` then reload; (3) remove the `remove` accounts on both nodes (`pkill`, `userdel` without `-r`, `groupdel`, `sacctmgr delete user`) — home and `/shared` data untouched; (4) print the list of usernames + UIDs so admins can recreate/reconnect them (spec §5.5).
  - `rollback.sh --check|--apply <snapshot dir>`: before `retire-tui`, restores the removed accounts from the snapshot (refuses and lists any UID/username now used by a web account), restores the sshd drop-in, re-adds Slurm associations from the dump.
  - `retire-tui.sh --check|--apply` (after the settling period): stops and disables `slurm-deck-audit`, removes `/opt/slurm-deck`, `/usr/local/bin/slurm-deck*` gateway/launcher, the legacy sudoers files; keeps backups.
  - `cutover-runbook.md`: dates, the exact command order, who is told what, how to verify each step, how to roll back.

- [ ] **Step 1:** Tests on fixture snapshots: a user in `gpuusers` with a real shell and not in `shellusers` → `remove`; a user in both `gpuusers` and the shell list → `flagged`; sysadmins never in `remove`; rollback refuses when a web account holds a removed user's UID; `cutover.sh --check` changes nothing (fake commands not called).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `<KEY>: add cutover snapshot, classification, cutover, rollback and TUI retirement`.

---

## Phase exit check

- [ ] Full install on a fresh test VM pair from `install.sh` only; acceptance run green; a cutover `--check` against a copy of the real cluster's snapshot reviewed by the owner before any `--apply` on the live cluster.
