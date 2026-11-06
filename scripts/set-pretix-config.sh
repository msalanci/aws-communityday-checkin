#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Writes the two non-secret pretix settings the Lambdas read: the organizer slug and the check-in list ID.
#
# Usage: scripts/set-pretix-config.sh [--organizer <slug>] [--list <id>]
#
# Terraform creates both SSM parameters with a placeholder and never changes their values; this script
# sets them. The Lambdas use a new value within 5 minutes.

set -euo pipefail
source "$(dirname "$0")/common.sh"

# Reads the options and writes the parameters given.
# Arguments:
#   $@ - "--organizer <slug>" and/or "--list <id>"
# Returns:
#   0 after SSM stored each given value; exits through fail on a wrong or missing value.
main() {
  local organizer="" list_id="" prefix
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --organizer)
        organizer="${2:-}"
        [[ "$organizer" =~ ^[a-z0-9][a-z0-9-]*$ ]] || fail "--organizer needs a pretix organizer slug, for example my-community"
        shift 2
        ;;
      --list)
        list_id="${2:-}"
        [[ "$list_id" =~ ^[0-9]+$ ]] || fail "--list needs the check-in list's number, for example 123456"
        shift 2
        ;;
      *)
        fail "usage: scripts/set-pretix-config.sh [--organizer <slug>] [--list <id>]"
        ;;
    esac
  done
  [[ -n "$organizer" || -n "$list_id" ]] || fail "usage: scripts/set-pretix-config.sh [--organizer <slug>] [--list <id>]"
  load_outputs
  prefix="$(tf_output ssm_prefix)"
  if [[ -n "$organizer" ]]; then
    aws ssm put-parameter --name "$prefix/pretix/organizer" --type String --overwrite --value "$organizer" --output text > /dev/null
    printf 'Set %s/pretix/organizer to %s\n' "$prefix" "$organizer"
  fi
  if [[ -n "$list_id" ]]; then
    aws ssm put-parameter --name "$prefix/pretix/checkin-list-id" --type String --overwrite --value "$list_id" --output text > /dev/null
    printf 'Set %s/pretix/checkin-list-id to %s\n' "$prefix" "$list_id"
  fi
}

main "$@"
