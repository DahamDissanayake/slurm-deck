#!/bin/sh
# Install Slurm Deck on the login node: run as slurmadmin. Rerun after a
# failure to resume. Options: --check, --answers FILE, --accept-small.
cd "$(dirname "$0")" && exec sudo python3 -m deploy.installer "$@"
