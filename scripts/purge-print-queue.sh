#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Deletes every waiting print request: for stickers nobody asked for (a misused staff PIN).
#
# Usage: scripts/purge-print-queue.sh
#
# Change the staff PIN first (set-secrets.sh --pin), then purge, then restart the print laptop's
# program. Purged requests are gone; real attendees can be reprinted from the scanner page.

set -euo pipefail
source "$(dirname "$0")/common.sh"

# Purges the print queue after a typed confirmation.
# Arguments:
#   None.
# Returns:
#   0 after the purge was requested.
main() {
  local url region
  load_outputs
  url="$(tf_output print_queue_url)"
  region="$(tf_output aws_region)"
  confirm "This deletes every print request waiting in $url." "purge"
  aws sqs purge-queue --region "$region" --queue-url "$url"
  printf 'Purge requested; SQS finishes it within 60 seconds.\n'
}

main "$@"
