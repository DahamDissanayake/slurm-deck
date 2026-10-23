# Slurm Deck

A browser-based platform for running work on a shared GPU cluster managed by
Slurm. Users sign in with an email and password, then submit and schedule jobs,
open JupyterLab sessions, upload large datasets and manage their files from one
dashboard, without needing SSH. It runs on the campus LAN.

**Status:** in development. The design is in
[`docs/specs/2026-10-23-web-platform-design.md`](docs/specs/2026-10-23-web-platform-design.md).

## Previous version

The earlier SSH terminal (TUI) version, v1.4, lives on the
[`legacy/v1.4-tui`](https://github.com/DahamDissanayake/slurm-deck/tree/legacy/v1.4-tui)
branch. That is the branch to deploy and maintain until the web platform
replaces it.

## Contributing

See [`CLAUDE.md`](CLAUDE.md) for how work is tracked, the branch model, and the
rules every change follows.

## License

MIT. See [`LICENSE`](LICENSE).
