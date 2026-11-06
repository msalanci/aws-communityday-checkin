#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Shared helpers for the scripts that talk to AWS: reading Terraform's outputs and asking for confirmation.
#
# Sourced by the other scripts, never run on its own. The scripts take every AWS name from
# "terraform output" of infrastructure/, so nothing is hard-coded, and they run with the AWS CLI's
# default profile: the account the app runs in. A script calls load_outputs once, then assigns each
# value with name="$(tf_output name)" on its own line, so a missing output stops it.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK="$ROOT/infrastructure"
OUTPUTS=""

# Prints an error to stderr and stops the script.
# Arguments:
#   $1 - the message
# Returns:
#   Never returns; exits with status 1.
fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

# Reads every output of the app stack once, showing Terraform's own message when that fails.
# Arguments:
#   None.
# Returns:
#   0 after filling OUTPUTS with the outputs as JSON; exits through fail when Terraform fails
#   (for example expired credentials for the state bucket, or terraform init not run).
load_outputs() {
  local errors
  errors="$(mktemp)"
  if ! OUTPUTS="$(terraform -chdir="$STACK" output -json 2>"$errors")"; then
    cat "$errors" >&2
    rm -f "$errors"
    fail "terraform output failed in $STACK; see Terraform's message above"
  fi
  rm -f "$errors"
}

# Prints one output that load_outputs read.
# Arguments:
#   $1 - the output's name
# Returns:
#   0, printing the value; exits through fail when the stack has no such output yet.
tf_output() {
  python3 -c 'import json, sys
outputs = json.loads(sys.argv[1] or "{}")
if sys.argv[2] not in outputs:
    sys.exit(1)
print(outputs[sys.argv[2]]["value"])' "$OUTPUTS" "$1" \
    || fail "terraform output $1 does not exist in $STACK; apply the app stack first"
}

# Asks for a typed word before a step that cannot be undone.
# Arguments:
#   $1 - what will happen
#   $2 - the word to type
# Returns:
#   0 when the word was typed; exits through fail otherwise.
confirm() {
  local answer
  printf '%s Type %s to go on: ' "$1" "$2" >&2
  read -r answer
  [[ "$answer" == "$2" ]] || fail "cancelled"
}
