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

# Fail before anything touches the inverter if the log cannot be written: the
# caller reports from this log, so a run it cannot record must not happen.
if ! mkdir -p "$PROJECT_ROOT/data" 2>/dev/null || ! { : >> "$LOG"; } 2>/dev/null; then
  echo "cannot write $LOG; refusing to run" >&2
  exit 1
fi

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
# `pip install` exists AND it records the hash of the requirements.txt that was
# installed; a changed requirements.txt or a venv that failed part-way is
# rebuilt instead of running the script against missing packages.
STAMP="$VENV/.requirements-installed"
WANT="$(sha256sum "$PROJECT_ROOT/requirements.txt" | cut -d' ' -f1)"
log_header "$@"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT" ]; then
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
  printf '%s\n' "$WANT" > "$STAMP"
fi

output="$("$VENV/bin/python" "$PROJECT_ROOT/scripts/nightly-charge.py" "$@" 2>&1 | tee -a "$LOG"; exit "${PIPESTATUS[0]}")"
status=$?

# Final line of the script's output is the one-line result the caller reports.
printf '%s\n' "$output" | tail -n 1
exit "$status"
