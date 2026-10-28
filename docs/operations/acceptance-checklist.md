# Acceptance run (spec §13)

The §13 scenarios are checked two ways: an automated API-level run
(`tests/e2e/test_scenarios.py`) against a real install, and a manual checklist
for what only a person can check. Record both in the pull request or release
notes of the run.

The run is safe on a cluster people are using: it uses throwaway accounts only,
every job asks for no GPU pod, 1 CPU, 1–2 GB and at most 15 minutes, and
scenario 12 (drain and resume) only runs when you allow it.

## Automated run

Run it on the login node as the admin user (it reads one-time links from the
outbox with `sudo docker exec`), from a checkout outside `/opt`.

1. **Throwaway admin.** In `<install>/deploy`:

   ```bash
   sudo docker compose run --rm web python -m sdweb.cli create-admin --force \
     --email 'delivered+sdtestadmin@resend.dev' --full-name 'Acceptance admin' \
     --username sdtestadmin
   echo sdtestadmin | sudo tee -a /etc/slurm-deck-web/admins
   ```

   Open the printed link's token with `POST /api/auth/password/set` (or in a
   browser) to give it a password.

2. **Returning user for scenario 11 (optional).** On the GPU host, as root, make
   an old folder owned by a UID nobody has (outside the web UID range):

   ```bash
   d=<nfs export>/users/sdtestback
   mkdir -p "$d/PlurVa" && echo "returning user's project" > "$d/PlurVa/notes.txt"
   chown -R 19990:<admin group> "$d" && chmod 2770 "$d"
   ```

   Check first that `getent passwd 19990` is empty on both nodes. Without this
   step scenario 11 is skipped.

3. **Run**, with Python 3.11+, `httpx` and `pytest` in a virtualenv:

   ```bash
   SD_E2E=1 SD_E2E_URL=https://<public hostname> SD_E2E_CONNECT=127.0.0.1 \
   SD_E2E_ADMIN_EMAIL='delivered+sdtestadmin@resend.dev' SD_E2E_ADMIN_PASSWORD=... \
   SD_E2E_RETURNING_USER=sdtestback \
   pytest tests/e2e/test_scenarios.py -v
   ```

   Other settings (size of the scenario 2 upload, waits, `SD_E2E_DISRUPTIVE=1`
   for scenario 12) are listed in `tests/e2e/conftest.py`. Job scenarios wait
   for the node, so run them when it isn't full.

4. **Clean up.** The fixture deletes every account it made (with their files,
   Linux users on both nodes, Slurm associations and jobs). Then:
   - remove the archive scenario 14 leaves: `<nfs export>/users/sdtestdel.offboarded`
     (GPU host, as root);
   - remove `sdtestadmin` from `/etc/slurm-deck-web/admins`;
   - a real admin deletes `sdtestadmin` in Admin → Accounts (an admin can't
     delete their own account).

| # | Scenario | Automated check |
|---|---|---|
| 1 | Notebook | session ready; proxied `/api/status` 200; scratch file made and deleted |
| 2 | Big upload | stand-in upload (20 GB by default) interrupted mid-chunk, resumed from `HEAD`, size matches |
| 3 | Extend | +1 h allowed and shown; repeated +4 h refused with `over_cap` |
| 4 | Host OOM | job holding 3 GB in 1 GB ends `OUT_OF_MEMORY` with the explanation |
| 5 | Sweep | array `0-3%2` after a dependency; history shows all four tasks |
| 6 | TensorBoard | owner gets 200; the other user gets 403 "not your session" |
| 7 | Build an env | venv from a `requirements.txt` with `tensorboard`; build ok, nothing missing |
| 9 | GPU full | notify subscription mails once and is consumed |
| 10 | Outsider | allow-listed address applies and is approved; a gmail address is refused |
| 11 | Returning user | preview finds the folder; account reconnects with its UID; file readable |
| 12 | Maintenance | drain (no cancel) and resume, both in deck-agent's audit log |
| 14 | Account removed | delete archives the folder; the next account gets a new, higher UID |

## Manual checklist

Fill in date, who and result for each run.

| Check | How | Result |
|---|---|---|
| 8. Gated model | With a real HuggingFace token that has access, download a gated model (e.g. a `meta-llama/...` repo) from Models. It runs as a Slurm job, can be resumed, and lands in the user's area. | |
| 13. Shell user unchanged | As an existing shell user: `ssh` to the login node, `sbatch` a small job, `rsync` a file in and out. All work exactly as before. | |
| Certificate | After trusting the site CA, the app and a session tab open with no certificate warning. | |
| Dark and light | Switch the theme; every page reads well in both. | |
| New tabs | Open on a notebook, TensorBoard and terminal opens each in a new tab. | |
