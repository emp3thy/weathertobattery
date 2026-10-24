#!/usr/bin/env bash
# run-nightly.sh — what the NanoClaw task calls each night.
#
# Runs scripts/nightly-charge.py from the project root inside a venv that this
# script owns (<project>/.venv), creating it from requirements.txt when missing.
# Appends a timestamped header plus the script's combined output to
# data/nightly.log, prints the script's final output line to stdout, and exits
# with the script's exit status. Any extra arguments (e.g. --dry-run) are passed
# straight through to nightly-charge.py.
#
# Works from any working directory, and both inside the agent container and on
# the Ubuntu host.
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

VENV="$PROJECT_ROOT/.venv"
LOG="$PROJECT_ROOT/data/nightly.log"
mkdir -p "$PROJECT_ROOT/data"

# Behind the NanoClaw/OneCLI proxy every HTTPS connection is re-signed with the
# gateway's CA. curl and httpx read SSL_CERT_FILE; requests (used by the Growatt
# client) and pip do not, so point them at the same bundle.
if [ -n "${SSL_CERT_FILE:-}" ]; then
  export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
  export PIP_CERT="$SSL_CERT_FILE"
  export CURL_CA_BUNDLE="$SSL_CERT_FILE"
fi

log_header() {
  printf '=== %s run-nightly %s ===\n' "$(date -Is)" "$*" >> "$LOG"
}

# A venv counts as ready only when the stamp written after a successful
# `pip install` exists; a venv that failed part-way is removed so the next run
# rebuilds it instead of running the script against missing packages.
STAMP="$VENV/.requirements-installed"
log_header "$@"
if [ ! -f "$STAMP" ]; then
  rm -rf "$VENV"
  {
    echo "creating venv at $VENV"
    python3 -m venv "$VENV" && "$VENV/bin/pip" install -q -r "$PROJECT_ROOT/requirements.txt"
  } >> "$LOG" 2>&1
  status=$?
  if [ "$status" -ne 0 ]; then
    rm -rf "$VENV"
    echo "venv setup failed (exit $status); see $LOG" >&2
    tail -n 5 "$LOG" >&2
    exit "$status"
  fi
  touch "$STAMP"
fi

output="$("$VENV/bin/python" "$PROJECT_ROOT/scripts/nightly-charge.py" "$@" 2>&1 | tee -a "$LOG"; exit "${PIPESTATUS[0]}")"
status=$?

# Final line of the script's output is the one-line result the caller reports.
printf '%s\n' "$output" | tail -n 1
exit "$status"
