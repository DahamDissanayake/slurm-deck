# CLAUDE.md

Guidance for every agent and contributor working in this repository.

## Where work comes from

Work on this repo is planned and tracked in **SerenEdge**. Each change starts
from a SerenEdge task or issue, which has a key (for example `PROJ-42`). Pick
up work through SerenEdge, build it on its own branch, and hand it back through
a pull request for review. Don't start untracked work.

The current direction is the browser-based platform described in
`docs/specs/2026-10-23-web-platform-design.md`. It replaces the SSH TUI for
normal users and admins. Read it before working on anything web-related.

## Branches

- **`main`**: release branch, and what the live cluster deploys from
  (`deploy/redeploy-slurm-deck.sh` fast-forwards `/opt/slurm-deck` to it).
  Never commit to it directly. It changes only when `dev` is merged into it at
  a release point.
- **`dev`**: the integration branch where day-to-day work lands.
- **Task and issue branches**: every change gets its own short-lived branch off
  `dev`, merged back into `dev` by pull request, then deleted.
  - Task work: `task/<KEY>-<short-slug>`, e.g. `task/PROJ-42-add-due-dates`
  - Bug or issue work: `issue/<KEY>-<short-slug>`, e.g. `issue/PROJ-57-login-error`

```
main  ◄── release merge ──  dev  ◄── PR ──  task/PROJ-42-add-due-dates
                                 ◄── PR ──  issue/PROJ-57-login-error
```

## Rules

1. Work only on a `task/<KEY>-<short-slug>` or `issue/<KEY>-<short-slug>`
   branch cut from `dev`, and open a pull request into `dev`. Never commit
   straight to `main`.
2. Commit messages are `<KEY>: short imperative summary`, e.g.
   `PROJ-42: add due dates`.
3. Never add a `Co-Authored-By` trailer, a "Generated with" line, or any AI or
   agent attribution to commits, pull requests, code comments or docs.
4. Never commit secrets or a `.env` file. Site config (`deploy/site.env`) and
   secrets (`deploy/secrets.env`) are gitignored; use the `.example` files as
   templates.
5. Don't add new frameworks or dependencies without asking first. Runtime
   Python dependencies are listed in `requirements.txt` (the single source of
   truth, checked by `tests/test_dependencies.py`).
6. Keep changes small and tied to one task.

## Working notes

- Run the tests on Linux. The suite imports `grp`/`fcntl`, and on a Windows
  checkout with `core.autocrlf=true` the shell scripts get CRLF line endings,
  which breaks `set -o pipefail`. In Docker: copy the repo in, strip `\r` from
  the files, `pip install -r requirements.txt pytest tzdata`, and run
  `python -m pytest -q` as a non-root user. Daemon permission tests pass for
  the wrong reason when run as root.
- Nothing site-specific is hardcoded in `slurmdeck/` (IPs, hostnames, ports,
  timezone). Those values come from `deploy/site.env` via `slurmdeck/config.py`.
  `tests/test_no_hardcoded_site_values.py` enforces this.
