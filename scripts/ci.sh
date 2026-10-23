#!/usr/bin/env bash
# Local CI, run by `serenedge ci` (see .serenedge/ci.json) and by the GitHub
# workflow on pull requests into main.
#
# Steps: lint, typecheck, unit, integration, root, build. Each prints
# `==> STEP <name>` plus the `::serenedge-step` markers that `serenedge ci`
# reports on. The run stops at the first failing step.
#
# On a machine that isn't Linux, the whole run is repeated inside a
# python:3.11-slim container as a non-root user (needs Docker).
#
# Integration tests use TEST_DATABASE_URL. When it is unset and Docker is
# available, a throwaway postgres:16 container is started for the run.
set -euo pipefail

cd "$(dirname "$0")/.."

PY_IMAGE="python:3.11-slim"
PG_IMAGE="postgres:16"
RUN_ID="sdci-$$-$RANDOM"
PG_CONTAINER=""
NETWORK=""

cleanup() {
    if [ -n "$PG_CONTAINER" ]; then docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true; fi
    if [ -n "$NETWORK" ]; then docker network rm "$NETWORK" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

have_docker() {
    command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

# Start postgres:16 and wait until it accepts connections.
# $1: extra `docker run` arguments (a network or a port mapping).
start_postgres() {
    PG_CONTAINER="$RUN_ID-pg"
    # shellcheck disable=SC2086
    docker run -d --rm --name "$PG_CONTAINER" $1 \
        -e POSTGRES_PASSWORD=ci -e POSTGRES_DB=sdtest "$PG_IMAGE" >/dev/null
    for _ in $(seq 1 60); do
        if docker exec "$PG_CONTAINER" pg_isready -U postgres -d sdtest >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "postgres did not become ready" >&2
    return 1
}

if [ "$(uname -s)" != "Linux" ] && [ -z "${SDCI_IN_CONTAINER:-}" ]; then
    if ! have_docker; then
        echo "CI needs Linux. On this machine it runs in a container, but Docker is not running." >&2
        exit 1
    fi
    NETWORK="$RUN_ID-net"
    docker network create "$NETWORK" >/dev/null
    db_url="${TEST_DATABASE_URL:-}"
    if [ -z "$db_url" ]; then
        start_postgres "--network $NETWORK"
        db_url="postgresql://postgres:ci@$PG_CONTAINER:5432/sdtest"
    fi
    # The checkout is mounted read-only and copied, so CRLF can be stripped
    # without touching the working tree.
    MSYS_NO_PATHCONV=1 docker run --rm --network "$NETWORK" \
        -v "$(pwd -W 2>/dev/null || pwd):/src:ro" \
        -e SDCI_IN_CONTAINER=1 -e TEST_DATABASE_URL="$db_url" \
        "$PY_IMAGE" bash -c '
            set -euo pipefail
            useradd -m ci
            cp -r /src /work
            find /work -path /work/.git -prune -o -type f -print0 | xargs -0 sed -i "s/\r$//"
            chown -R ci:ci /work
            su ci -c "python -m venv /home/ci/venv && /home/ci/venv/bin/pip install -q -e /work[web,agent,dev]"
            exec su ci -c "PATH=/home/ci/venv/bin:\$PATH bash /work/scripts/ci.sh"
        '
    exit $?
fi

step() {
    local name="$1"
    shift
    echo "==> STEP $name"
    echo "::serenedge-step name=$name status=start::"
    if "$@"; then
        echo "::serenedge-step name=$name status=pass::"
    else
        echo "::serenedge-step name=$name status=fail::"
        exit 1
    fi
}

# pytest exits 5 when no test matched the marker; that is not a failure.
pytest_marked() {
    local rc=0
    "$@" || rc=$?
    [ "$rc" -eq 0 ] || [ "$rc" -eq 5 ]
}

# gpuhost/ arrives with the GPU-host helper; include it once it exists.
EXTRA_PATHS=()
if [ -d gpuhost ]; then EXTRA_PATHS+=(gpuhost); fi

lint() { ruff check src tests "${EXTRA_PATHS[@]}"; }

typecheck() { mypy src/sdcore src/deckagent src/sdweb; }

unit() { pytest_marked pytest -q -m "not root and not pg"; }

integration() {
    if [ -z "${TEST_DATABASE_URL:-}" ]; then
        if ! have_docker; then
            echo "TEST_DATABASE_URL is unset and Docker is not available" >&2
            return 1
        fi
        start_postgres "-p 127.0.0.1::5432"
        local port
        port="$(docker port "$PG_CONTAINER" 5432/tcp | head -n1 | sed 's/.*://')"
        export TEST_DATABASE_URL="postgresql://postgres:ci@127.0.0.1:$port/sdtest"
    fi
    pytest_marked pytest -q -m pg
}

root() {
    if [ "$(id -u)" -eq 0 ]; then
        pytest_marked pytest -q -m root
    elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        pytest_marked sudo -n -E env "PATH=$PATH" pytest -q -m root
    else
        echo "SKIPPED (no passwordless sudo)"
    fi
}

build() { python -m compileall -q src "${EXTRA_PATHS[@]}"; }

step lint lint
step typecheck typecheck
step unit unit
step integration integration
step root root
step build build
