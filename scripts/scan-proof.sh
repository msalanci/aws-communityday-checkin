#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Checks the scan API end to end against the real system, with one test ticket.
#
# Usage: scripts/scan-proof.sh <ticket secret>
#
# Asks for the staff PIN without showing it, then calls POST <scanner_url>/api/scan five times:
#   1. a wrong PIN                     → 401 "Wrong PIN"
#   2. the ticket with a new nonce     → checked_in: it is checked in and one sticker prints
#   3. the same request again          → checked_in again, same print ID: the laptop shows "already printed"
#   4. the ticket with another nonce   → already_checked_in, with the time
#   5. an unknown secret               → invalid
# It checks the ticket in on the live list: use only a test registration that is cancelled before the
# event. The PIN reaches curl through a temporary file only this user can read, never a command line.

set -euo pipefail
source "$(dirname "$0")/common.sh"

HEADER_FILE=""

# Removes the temporary header file, if there is one.
# Arguments:
#   None.
# Returns:
#   0.
cleanup() {
  [[ -z "$HEADER_FILE" ]] || rm -f "$HEADER_FILE"
}

# Prints a new nonce.
# Arguments:
#   None.
# Returns:
#   0, printing a lowercase UUID.
new_nonce() {
  uuidgen | tr '[:upper:]' '[:lower:]'
}

# Sends one scan and prints its HTTP status and body.
# Arguments:
#   $1 - what this call checks
#   $2 - the scanner URL
#   $3 - the file with the X-Staff-Pin header
#   $4 - the ticket secret
#   $5 - the nonce
# Returns:
#   0 after printing one line; curl's own errors stop the script.
scan_line() {
  local body answer
  body="$(python3 -c 'import json, sys; print(json.dumps({"secret": sys.argv[1], "nonce": sys.argv[2]}))' "$4" "$5")"
  answer="$(curl -sS --max-time 15 -X POST "$2/api/scan" -H "Content-Type: application/json" -H "@$3" \
    --data "$body" -w '\nHTTP %{http_code}')"
  printf '%s\n  %s\n  %s\n' "$1" "$(tail -n 1 <<< "$answer")" "$(sed '$d' <<< "$answer")"
}

# Runs the five checks.
# Arguments:
#   $1 - the test ticket's secret
# Returns:
#   0 after all five calls.
main() {
  local secret="${1:-}" url pin nonce wrong_file
  [[ -n "$secret" ]] || fail "usage: scripts/scan-proof.sh <ticket secret>"
  trap cleanup EXIT
  load_outputs
  url="$(tf_output scanner_url)"
  confirm "This checks the ticket in on the live check-in list at $url. Use a test registration only." "yes"
  read -r -s -p "Staff PIN (it is not shown): " pin
  printf '\n'
  [[ -n "$pin" ]] || fail "no PIN given"
  HEADER_FILE="$(mktemp)"
  chmod 600 "$HEADER_FILE"
  wrong_file="$HEADER_FILE.wrong"
  printf 'X-Staff-Pin: %s\n' "$pin" > "$HEADER_FILE"
  printf 'X-Staff-Pin: not-the-pin\n' > "$wrong_file"
  nonce="$(new_nonce)"
  scan_line "1. Wrong PIN (expect 401):" "$url" "$wrong_file" "$secret" "$nonce"
  rm -f "$wrong_file"
  scan_line "2. Scan (expect checked_in; one sticker prints):" "$url" "$HEADER_FILE" "$secret" "$nonce"
  scan_line "3. Same request again (expect checked_in; the laptop shows already printed):" "$url" "$HEADER_FILE" "$secret" "$nonce"
  scan_line "4. Scan again (expect already_checked_in with the time):" "$url" "$HEADER_FILE" "$secret" "$(new_nonce)"
  scan_line "5. Unknown ticket (expect invalid):" "$url" "$HEADER_FILE" "no-such-ticket-$(new_nonce)" "$(new_nonce)"
}

main "$@"
