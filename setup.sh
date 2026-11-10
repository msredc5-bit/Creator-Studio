#!/usr/bin/env bash
# Creator Studio — one-command setup (thin wrapper around setup.py).
#
#   bash setup.sh [--check] [--target DIR] [--force]
#
# setup.py does the work (stdlib only, no network, no keys, $0).
# This wrapper exists only so a missing python3 gives a clear
# error instead of a bare "command not found".
set -e
if ! command -v python3 >/dev/null 2>&1; then
    echo "setup.sh: ERROR: python3 is not installed." >&2
    echo "Install Python 3.10+ from https://www.python.org/downloads/" >&2
    echo "then re-run: bash setup.sh" >&2
    exit 2
fi
exec python3 "$(dirname "$0")/setup.py" "$@"
