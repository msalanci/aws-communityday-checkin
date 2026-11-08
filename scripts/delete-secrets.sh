#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Deletes the two secret SSM parameters, the pretix token and the staff PIN: the teardown after the event.
#
# Usage: scripts/delete-secrets.sh
#
# Within 5 minutes the scan_reprint Lambda stops working (it answers "call the organizer"): a warm Lambda
# keeps the values it read for up to 5 minutes. The two non-secret parameters belong to Terraform and go
# with terraform destroy.

set -euo pipefail
source "$(dirname "$0")/common.sh"

# Deletes both secret parameters after a typed confirmation.
# Arguments:
#   None.
# Returns:
#   0 after SSM deleted them; names that did not exist are listed, not an error.
main() {
  local prefix region result
  load_outputs
  prefix="$(tf_output ssm_prefix)"
  region="$(tf_output aws_region)"
  confirm "This deletes $prefix/pretix/token and $prefix/staff-pin." "delete"
  result="$(aws ssm delete-parameters --region "$region" --names "$prefix/pretix/token" "$prefix/staff-pin" \
    --query '[join(`, `, DeletedParameters), join(`, `, InvalidParameters)]' --output text)"
  printf 'Deleted, then did not exist (tab-separated): %s\n' "$result"
}

main "$@"
