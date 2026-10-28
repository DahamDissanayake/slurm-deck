# Cutover runbook: from the SSH TUI to the web platform

The old users lose their login-node accounts; their folders (`/shared/users/<name>`,
`/shared/jobs/<name>`) stay where they are and are reconnected when an admin creates the web
account (design §5.5, §12). The tools are in `deploy/cutover/`. Every one of them can be run
as `--check` first, and `--check` changes nothing.

Run everything as root on the node named. `SYSADMINS` is the comma-separated list of
people who must always keep ssh (never removed). Set `SYSADMIN_GROUP` to the group they
belong to, and `PUBLIC_HOSTNAME` is in `/etc/slurm-deck-web/site.env`.

## 0. At install: cluster hardening (design §10)

The installer's `harden` step runs the scripts in `deploy/cluster/harden/` as root, from a
root-owned copy in `/usr/local/lib/slurm-deck/cluster/harden/` on each node. It runs every
`--check` first and prints the output, then runs `--apply` only when you confirm (answer `y`,
or pass `--apply-hardening`). Until it has been applied the install doesn't finish: the
installer stops with an error, and the next run resumes at `harden`.

The scripts get `NFS_ROOT` and `SYSADMINS` from the site values (`nfs_root`, `sysadmins`).
In this order:

| # | Script | Node | `--check` shows | `--apply` does |
|---|--------|------|-----------------|----------------|
| 1 | `remove-docker-group.sh` | login node, then GPU host | the `docker` members, who would be removed, the running containers | removes everyone but `SYSADMINS`, plus the admin account that runs docker compose (login node) and the GPU admin login if it isn't root |
| 2 | `service-accounts.sh` | login node, then GPU host | whether `sd-stats` exists, the legacy units still installed | creates `sd-stats`, disables `slurm-deck-stats` and `slurm-deck-pod-notify.timer`, runs `sd-stats-writer` as `sd-stats` where `nvidia-smi` exists |
| 3 | `shared-areas.sh` | GPU host (the NFS server) | per area under `NFS_ROOT`, counts of wrong owners, directory modes, writable files, `gpuusers` ACLs | owner `sd-ops:gpuadmins`, directories `2775`, no group/other write on files, `gpuadmins` ACLs; never `users/` or `jobs/` |

Before you confirm, read the `--check` output:

- **Docker group:** every person who must keep `docker` is in `sysadmins`. If `SYSADMINS` is
  empty and the GPU admin login is root, `--apply` refuses on the GPU host. Stop any running
  container a removed user still needs. Their open sessions keep the group until they log out.
- **Shared areas:** the counts are what you expect, and `sd-ops` exists (the installer creates
  it in `gpuhost_bootstrap`).
- **Service accounts:** the TUI's pod notifications stop when the timer is disabled.

After `--apply`, check on each node. `getent group docker` lists only the sysadmins.
`--check` again shows nothing to remove and zero counts. A normal user can't write
`$NFS_ROOT/envs`. `systemctl show -p User sd-stats-writer` prints `User=sd-stats` on the GPU host.

To run a script by hand: `sudo NFS_ROOT=/shared SYSADMINS=amasha,dinuka
/usr/local/lib/slurm-deck/cluster/harden/<script> --check` (then `--apply`).

## 1. A week or more before: decide who is who

On the login node and on the GPU host:

```bash
sudo deploy/cutover/snapshot.sh /var/backups/slurm-deck/cutover-<date>
```

It copies `passwd`, `shadow`, `group`, `gshadow` and the ssh drop-ins (and, on the login node,
a Slurm accounting dump) to `<dir>/<node>/`, readable by root only. Keep the folder: rollback
needs it. Then, on the login node:

```bash
SYSADMINS=amasha,dinuka SHELL_USERS=hassan deploy/cutover/classify.py /var/backups/slurm-deck/cutover-<date>
```

`cutover-plan.json` lists who would be removed, who keeps a shell, the sysadmins, the service
accounts and `flagged` people. **Read the flagged ones**: someone in a GPU group *and* on the
shell list is never removed automatically. Decide for each (add them to `SHELL_USERS` or take
them out of the GPU group), take a new snapshot and classify again until `flagged` is empty.

## 2. Announce (days before)

```bash
CUTOVER_DATE=2026-11-09 deploy/cutover/cutover.sh --announce --check <dir>/cutover-plan.json
CUTOVER_DATE=2026-11-09 deploy/cutover/cutover.sh --announce --apply <dir>/cutover-plan.json
```

This puts a banner on every page of the web app and writes `announce-recipients.txt`
(addresses from the old `users.db`, only for the people who will lose their account). Email
them yourself: the date, that their old login stops, that an admin will make their new
account, and that their files are kept.

## 3. Cutover day

Before you start: the web app is up, you can sign in as an admin, the backup ran last night
(`systemctl list-timers sd-backup.timer`), and a fresh snapshot exists.

1. Login node: `cutover.sh --check <plan>`, read the list, then `cutover.sh --apply <plan>`.
   It closes the TUI logins first (disables the ForceCommand drop-in, allows ssh only for the
   shell group and `SYSADMIN_GROUP`, checks and reloads sshd), then removes the planned accounts
   without touching their folders. It prints each username with its UID.
2. GPU host: `cutover.sh --apply <plan> --no-sshd`.
3. Check: `ssh` as a removed user is refused; a sysadmin and a shell user can still log in;
   `getent passwd <removed user>` is empty; `ls /shared/users/<removed user>` still lists files;
   the web sign-in page loads.
4. Admins: **Admin → Users → New user** for each person who continues, choosing
   "reconnect their old folder" (it uses the UID printed in step 1). Each person gets an
   email to set a new password. Old job history is not imported; old job folders stay on disk.

## 4. If something is wrong: roll back

Only possible before step 5. On each node:

```bash
sudo deploy/cutover/rollback.sh --check /var/backups/slurm-deck/cutover-<date>
sudo deploy/cutover/rollback.sh --apply /var/backups/slurm-deck/cutover-<date>
```

It puts the removed accounts back from the snapshot, restores the ForceCommand drop-in, removes
the cutover's `AllowGroups`, and on the login node reloads the Slurm associations. It stops
with exit 3 and a list, changing nothing, if a web account now holds one of those usernames or
UIDs: sort that out (delete or move that web account in the admin pages) and run it again.

## 5. After the settling period

When nobody needs the TUI any more (a few weeks), on each node:

```bash
sudo deploy/cutover/retire-tui.sh --check
sudo deploy/cutover/retire-tui.sh --apply
```

It stops `slurm-deck-audit` and removes `/opt/slurm-deck`, the gateway and launchers, the old
sudoers files and the disabled ForceCommand drop-ins. **There is no rollback after this.** The
snapshots and the nightly backups stay, and so do all user folders. Folders of people who never
came back stay until an admin archives them.
