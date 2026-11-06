#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Deletes every access key of the print laptop's IAM user: for a lost, stolen or copied key.
#
# Usage: scripts/delete-print-laptop-keys.sh
#
# The print laptop stops receiving print requests at once; create a new key with
# create-print-laptop-key.sh and put it on the laptop to continue. Stops on any AWS error, so it never
# reports "no keys" when it could not look.

set -euo pipefail
source "$(dirname "$0")/common.sh"

# Lists the user's keys and deletes them after a typed confirmation.
# Arguments:
#   None.
# Returns:
#   0 after deleting the keys, or when there were none.
main() {
  local user ids key_id
  local -a keys
  load_outputs
  user="$(tf_output print_laptop_user_name)"
  ids="$(aws iam list-access-keys --user-name "$user" --query 'AccessKeyMetadata[].AccessKeyId' --output text)"
  read -r -a keys <<< "$ids"
  if [[ ${#keys[@]} -eq 0 ]]; then
    printf '%s has no access keys.\n' "$user"
    return 0
  fi
  confirm "This deletes ${#keys[@]} access key(s) of $user: ${keys[*]}." "delete"
  for key_id in "${keys[@]}"; do
    aws iam delete-access-key --user-name "$user" --access-key-id "$key_id"
    printf 'Deleted %s\n' "$key_id"
  done
}

main "$@"
