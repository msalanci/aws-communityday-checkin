#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Shows how many print requests wait in the print queue and in its dead-letter queue (DLQ).
#
# Usage: scripts/queue-status.sh
#
# "waiting" are ready to be taken; "in flight" were taken by the print laptop and are being printed.
# The DLQ should be empty; if not, fix the printer and run redrive-dlq.sh.

set -euo pipefail
source "$(dirname "$0")/common.sh"

# Prints the counts of one queue.
# Arguments:
#   $1 - the label to show
#   $2 - the queue URL
#   $3 - the region
# Returns:
#   0 after printing one line.
show() {
  local counts waiting in_flight
  counts="$(aws sqs get-queue-attributes --region "$3" --queue-url "$2" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes.[ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible]' --output text)"
  read -r waiting in_flight <<< "$counts"
  printf '%-12s waiting %s, in flight %s\n' "$1" "$waiting" "$in_flight"
}

# Shows both queues.
# Arguments:
#   None.
# Returns:
#   0 after printing both lines.
main() {
  local region queue_url dlq_url
  load_outputs
  region="$(tf_output aws_region)"
  queue_url="$(tf_output print_queue_url)"
  dlq_url="$(tf_output print_dlq_url)"
  show "Print queue:" "$queue_url" "$region"
  show "DLQ:" "$dlq_url" "$region"
}

main "$@"
