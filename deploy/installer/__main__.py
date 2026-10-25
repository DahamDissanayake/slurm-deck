"""python3 -m deploy.installer [--check] [--resume] [--answers FILE] [--accept-small]

Installs Slurm Deck on the login node. Progress is kept in
/etc/slurm-deck-web/install-state.json, so after a failure the same command
resumes at the step that failed (--resume says so, and is the default).
--check lists what would run and runs nothing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from deploy.installer import steps
from deploy.installer.state import DEFAULT_PATH, State


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deploy.installer", description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="show what would run; run nothing")
    ap.add_argument("--resume", action="store_true", help="continue a failed install (the default)")
    ap.add_argument("--answers", help="JSON file with the site values, instead of prompts")
    ap.add_argument("--accept-small", action="store_true",
                    help="go on when the login node is below 4 vCPUs, 12 GB RAM or has no swap")
    ap.add_argument("--state", default=DEFAULT_PATH, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    given = json.loads(Path(args.answers).read_text()) if args.answers else {}
    login: steps.Target = steps.Local()

    def gpu_target(answers: dict) -> steps.Target:
        return steps.SSH(answers["gpu_host"], answers["gpu_admin_user"], answers.get("gpu_admin_key", ""))

    ctx = steps.Ctx(login=login, gpu_target=gpu_target, state=State(args.state),
                    repo=Path(__file__).resolve().parents[2], check=args.check,
                    accept_small=args.accept_small)
    if args.check:
        ctx.login = steps.Dry(login, ctx.planned)
    try:
        steps.run_all(ctx, given)
    except steps.InstallError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.check:
        print("\nPlanned commands (nothing was run):")
        print("\n".join(f"  {c}" for c in ctx.planned))
    return 0


if __name__ == "__main__":
    sys.exit(main())
