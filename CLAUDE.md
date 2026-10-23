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

- **`main`**: release branch for the new web platform. Never commit to it
  directly. It changes only when `dev` is merged into it at a release point.
- **`dev`**: the integration branch where day-to-day work lands.
- **Task and issue branches**: every change gets its own short-lived branch off
  `dev`, merged back into `dev` by pull request, then deleted.
  - Task work: `task/<KEY>-<short-slug>`, e.g. `task/PROJ-42-add-due-dates`
  - Bug or issue work: `issue/<KEY>-<short-slug>`, e.g. `issue/PROJ-57-login-error`
- **`legacy/v1.4-tui`**: the previous SSH TUI codebase (v1.4), kept whole.
  The live cluster deploys from it until the web platform replaces it. Only
  critical fixes to the running TUI go there, and never new web work. Old
  specs, plans and dev-logs (M01–M05) also live there and are useful reference
  for the Slurm, storage and permission details the new platform reuses.

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
5. Don't add new frameworks or dependencies without asking first.
6. Keep changes small and tied to one task.

## Working notes

- The platform targets Linux (the login node). Run tests on Linux or in a
  Linux container. On a Windows checkout with `core.autocrlf=true`, shell
  scripts get CRLF line endings, which breaks bash (`set -o pipefail` fails),
  so strip `\r` before running them there.
- Nothing site-specific is hardcoded: IPs, hostnames, ports, email domains and
  timezone come from configuration or the admin panel, so other sites can run
  this as open source.

## CI

- Run `serenedge ci` before every push. It runs `scripts/ci.sh` (through
  `scripts/ci.mjs`): lint, typecheck, unit, integration, root and build, and
  stops at the first failure. Integration tests use `TEST_DATABASE_URL`, or a
  throwaway `postgres:16` container when it is unset and Docker is running.
- On a machine that isn't Linux, the script reruns itself inside a
  `python:3.11-slim` container as a non-root user, so Docker must be running.
- GitHub runs the same steps (`.github/workflows/ci.yml`) only on pull requests
  into `main`, not on `dev` or task branches.
- CI files (`scripts/ci.sh`, `scripts/ci.mjs`, `.serenedge/ci.json`,
  `.github/workflows/`) change only in tasks marked as CI changes.
