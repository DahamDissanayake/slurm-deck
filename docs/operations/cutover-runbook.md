# Cutover runbook: from the SSH TUI to the web platform

The old users lose their login-node accounts; their folders (`/shared/users/<name>`,
`/shared/jobs/<name>`) stay where they are and are reconnected when an admin creates the web
account (design §5.5, §12). The tools are in `deploy/cutover/`. Every one of them can be run
as `--check` first, and `--check` changes nothing.

Run everything as root on the node named. `SYSADMINS` is the comma-separated list of
people who must always keep ssh (never removed). Set `SYSADMIN_GROUP` to the group they
belong to, and `PUBLIC_HOSTNAME` is in `/etc/slurm-deck-web/site.env`.

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
