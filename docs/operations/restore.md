# Restoring a Slurm Deck backup

The nightly backup (`sd-backup.timer`, 02:30 in the cluster's timezone) writes two private
files per night to `/var/backups/slurm-deck/`, owned by `slurmadmin`, mode 0600:

- `sd-<YYYYmmdd>.dump`: the database, a `pg_dump -Fc` archive
- `sd-<YYYYmmdd>-config.tar.gz`: the `*.env` files and `install-state.json` from
  `/etc/slurm-deck-web/`, and the agent's audit log

It keeps the newest 14 (`BACKUP_KEEP`). With `BACKUP_COPY_TO_SHARED=1` in
`/etc/slurm-deck-web/backup.env` each night is also copied to `$NFS_ROOT/.admin-backups/`
(admins only). Nothing under `/shared/users` or `/shared/jobs` is part of this backup: those
are the users' files, and the web app never deletes them.

Check that it ran: `systemctl list-timers sd-backup.timer` and `journalctl -u sd-backup.service`.
Run one now: `sudo systemctl start sd-backup.service`.

## Restore the database

Run these as `slurmadmin` in the repository's `deploy/` folder. Pick the dump first:

```bash
ls -l /var/backups/slurm-deck/
DUMP=/var/backups/slurm-deck/sd-20261025.dump
```

1. Stop everything that writes to the database:

   ```bash
   docker compose stop web worker
   ```

2. Load the dump over the current database (this replaces its contents):

   ```bash
   docker compose exec -T db pg_restore -U sdweb -d slurmdeck --clean --if-exists --no-owner < "$DUMP"
   ```

   If the database is gone entirely (a fresh `pgdata` volume), start it first with
   `docker compose up -d db`, wait until it is healthy, and run the same command.

3. Start the app again; it migrates anything newer than the dump:

   ```bash
   docker compose up -d
   ```

4. Sign in, open **Admin → Monitoring → Audit** and check the last events are the ones you expect.
   Anything done after the dump was taken is lost, including accounts created since.

## Restore the config

Only needed on a rebuilt machine, or if a file in `/etc/slurm-deck-web/` was damaged:

```bash
sudo tar -xzf /var/backups/slurm-deck/sd-20261025-config.tar.gz -C /etc/slurm-deck-web \
    --exclude=agent-audit.jsonl
sudo chmod 0600 /etc/slurm-deck-web/agent.env
sudo chown root:root /etc/slurm-deck-web/agent.env
sudo chown slurmadmin:sdweb /etc/slurm-deck-web/web.env /etc/slurm-deck-web/secrets.env
sudo chmod 0640 /etc/slurm-deck-web/web.env /etc/slurm-deck-web/secrets.env
sudo chown root:root /etc/slurm-deck-web/install-state.json
sudo chmod 0600 /etc/slurm-deck-web/install-state.json
sudo systemctl restart deck-agent
```

`secrets.env` holds the database password, so restore it together with the dump taken the
same night. Restore `install-state.json` too before you run the installer again on a rebuilt
machine: it holds the generated passwords, and without it the installer would make new ones
that don't match the restored database. The audit log is in the archive for reading
(`tar -xzOf <archive> agent-audit.jsonl`); put it back at
`/var/log/slurm-deck-web/agent-audit.jsonl` only if that file is lost.

The upload grant key (`grant.key`) and the GPU-host key (`sdprov_ed25519`) are not in this
archive. The installer makes new ones if they are missing, and nothing is lost by that:
uploads in progress at that moment are simply restarted.
