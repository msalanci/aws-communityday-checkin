#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Sends one print request to the print queue, as a Lambda would: a test for the print laptop.
#
# Usage: scripts/send-test-print-request.sh [--id <id>] ["Full Name"]
#
# The last word of the name becomes the last name, as pretix would send it; the default name is
# "Ľubomír Šťastný". The ID is 1-64 letters, digits or hyphens (default: a new UUID). The same --id
# twice must print only once (the print laptop skips IDs it printed).

set -euo pipefail
source "$(dirname "$0")/common.sh"

# Prints how to use the script.
# Arguments:
#   None.
# Returns:
#   0 after printing the usage line.
usage() {
  printf 'Usage: scripts/send-test-print-request.sh [--id <id>] ["Full Name"]\n'
}

# Reads the options, builds the print request's JSON and sends it.
# Arguments:
#   $@ - optional "--id <id>" and an optional full name, in any order
# Returns:
#   0 after printing the print ID and the SQS message ID; exits through fail on an unknown option.
main() {
  local print_id="" name="" region url body message_id
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --id)
        [[ -n "${2:-}" ]] || fail "--id needs a value"
        print_id="$2"
        shift 2
        ;;
      -h | --help)
        usage
        return 0
        ;;
      -*)
        fail "unknown option $1 (see --help)"
        ;;
      *)
        [[ -z "$name" ]] || fail "give one name, in quotes: \"Ján Novák\""
        name="$1"
        shift
        ;;
    esac
  done
  [[ -n "$name" ]] || name="Ľubomír Šťastný"
  [[ -n "$print_id" ]] || print_id="$(uuidgen | tr '[:upper:]' '[:lower:]')"
  [[ "$print_id" =~ ^[A-Za-z0-9-]{1,64}$ ]] || fail "--id must be 1-64 letters, digits or hyphens"
  load_outputs
  region="$(tf_output aws_region)"
  url="$(tf_output print_queue_url)"
  body="$(python3 -c 'import json, sys
first, _, last = sys.argv[2].strip().rpartition(" ")
if not first:
    first, last = last, ""
print(json.dumps({"print_id": sys.argv[1], "first_name": first, "last_name": last}, ensure_ascii=False))' "$print_id" "$name")"
  message_id="$(aws sqs send-message --region "$region" --queue-url "$url" --message-body "$body" --query MessageId --output text)"
  printf 'Sent print request %s for "%s" (SQS message %s)\n' "$print_id" "$name" "$message_id"
}

main "$@"
