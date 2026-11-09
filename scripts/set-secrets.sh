#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Stores the two secrets the scan-print Lambda reads as SSM SecureStrings, outside Terraform, so they never
# reach its state.
#
# Usage: scripts/set-secrets.sh --token   asks for the pretix "lambda" token without showing it
#        scripts/set-secrets.sh --pin     asks for the staff PIN you want, typed twice without showing it;
#                                         Enter alone generates a random one and shows it once
#
# The Lambda uses a new value within 5 minutes; after a new PIN, staff type it on their phones again.
# A secret never appears on a command line: it reaches the AWS CLI through a temporary file only this
# user can read, deleted when the script ends.

set -euo pipefail
source "$(dirname "$0")/common.sh"

PIN_ALPHABET="ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
PIN_LENGTH=10
MIN_PIN_LENGTH=8
SECRET_FILE=""
REGION=""
PIN=""
GENERATED=""

# Removes the temporary secret file, if there is one.
# Arguments:
#   None.
# Returns:
#   0.
cleanup() {
  [[ -z "$SECRET_FILE" ]] || rm -f "$SECRET_FILE"
}

# Stores one SecureString parameter in the app's region (REGION) and tags it.
# Arguments:
#   $1 - the parameter's full name
#   $2 - the value
#   $3 - what it is, for the parameter's description
#   $4 - the project tag's value
# Returns:
#   0 after SSM stored and tagged it.
put_secret() {
  SECRET_FILE="$(mktemp)"
  chmod 600 "$SECRET_FILE"
  printf '%s' "$2" > "$SECRET_FILE"
  aws ssm put-parameter --region "$REGION" --name "$1" --type SecureString --overwrite --description "$3, set by script" \
    --value "file://$SECRET_FILE" --output text > /dev/null
  cleanup
  SECRET_FILE=""
  aws ssm add-tags-to-resource --region "$REGION" --resource-type Parameter --resource-id "$1" \
    --tags "Key=project,Value=$4" "Key=terraform,Value=no"
}

# Prints a new random staff PIN.
# Arguments:
#   None.
# Returns:
#   0, printing PIN_LENGTH characters from PIN_ALPHABET, which leaves out look-alikes (0 O o 1 I l).
new_pin() {
  python3 -c 'import secrets, sys
print("".join(secrets.choice(sys.argv[1]) for _ in range(int(sys.argv[2]))))' "$PIN_ALPHABET" "$PIN_LENGTH"
}

# Asks for the PIN the organizer wants, twice, or generates one when Enter alone is pressed.
# Arguments:
#   None.
# Returns:
#   0 after setting PIN, and GENERATED to "yes" for a random one; exits through fail when the two
#   entries differ or the PIN is too short, because the API is public and a short PIN can be
#   guessed within hours.
choose_pin() {
  local first second
  read -r -s -p "New staff PIN, at least $MIN_PIN_LENGTH letters or digits (Enter alone for a random one): " first
  printf '\n'
  if [[ -z "$first" ]]; then
    PIN="$(new_pin)"
    GENERATED="yes"
    return 0
  fi
  [[ "$first" =~ ^[A-Za-z0-9]+$ ]] || fail "use letters and digits only"
  (( ${#first} >= MIN_PIN_LENGTH )) || fail "the PIN needs at least $MIN_PIN_LENGTH characters"
  read -r -s -p "The same PIN again: " second
  printf '\n'
  [[ "$first" == "$second" ]] || fail "the two PINs differ; nothing was changed"
  PIN="$first"
}

# Sets the token or the PIN, as the option asks.
# Arguments:
#   $1 - --token or --pin
# Returns:
#   0 after storing the secret.
main() {
  local prefix tag token
  trap cleanup EXIT
  case "${1:-}" in
    --token | --pin) ;;
    *) fail "usage: scripts/set-secrets.sh --token | --pin" ;;
  esac
  load_outputs
  prefix="$(tf_output ssm_prefix)"
  tag="$(tf_output project_tag)"
  REGION="$(tf_output aws_region)"
  if [[ "$1" == "--token" ]]; then
    read -r -s -p "pretix token of the Lambda (it is not shown): " token
    printf '\n'
    [[ -n "$token" ]] || fail "no token given"
    put_secret "$prefix/pretix/token" "$token" "pretix API token of the scan-print Lambda" "$tag"
    printf 'Stored %s/pretix/token. The Lambda uses it within 5 minutes.\n' "$prefix"
  else
    choose_pin
    put_secret "$prefix/staff-pin" "$PIN" "Staff PIN of the scanner page" "$tag"
    printf 'Staff PIN stored. It works within 5 minutes; staff type it on their phones again.\n'
    [[ -z "$GENERATED" ]] || printf 'The generated PIN, shown only now: %s\n' "$PIN"
  fi
}

main "$@"
