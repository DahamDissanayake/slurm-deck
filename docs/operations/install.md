# Installing on the login node

Run the installer as the admin account (slurmadmin) from the checkout in
`/opt/slurm-deck-web`; `install.sh` runs it as root through sudo:

```
./install.sh --check --answers answers.json   # lists what would run, runs nothing
./install.sh --answers answers.json
```

Progress is kept in `/etc/slurm-deck-web/install-state.json` (root 0600), so after a
failure the same command resumes at the step that failed. The `accounts_login` and
`secrets` steps run on every run, so a newer installer rewrites the config files of an
existing install from the saved answers.

## Before you start

- Python 3.11 or newer with venv support. On Ubuntu that is the `python3-venv` package;
  without it `python3 -m venv` stops half-way, and `preflight` fails with
  "install python3-venv". If an earlier run left a venv with no `bin/pip`, the `agent`
  step removes it and makes it again.
- Docker with Compose v2, `nft`, and working `sinfo` and `munge`.

## Answers

`answers.json` holds the site values (see `SITE_FIELDS` in `deploy/installer/steps.py`).
Anything missing is asked on a terminal, or is an error without one.

Mail needs the credentials of the provider `mail_provider` names:

| `mail_provider` | Required answers | Optional |
|---|---|---|
| `resend` | `resend_api_key` | |
| `smtp` | `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password` | `smtp_starttls` (default `true`) |
| `none` | | |

On a terminal the key and the password are asked without echo. They are kept in the
install state with the other answers, written to `/etc/slurm-deck-web/secrets.env`
(admin:sdweb 0640) as `SD_RESEND_API_KEY` and `SD_SMTP_*`, left empty for the provider
not in use, and never shown by `--check`.

To add or change them on an install that is already past `site_values`, put them in the
answers file and run the installer again: the `secrets` step takes them and rewrites
`secrets.env`. Then restart the web stack (`docker compose up -d` in `deploy/`).

The cluster hardening the install ends with is in [cutover-runbook.md](cutover-runbook.md).
