#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Moves every print request from the dead-letter queue (DLQ) back to the print queue, so it prints.
#
# Usage: scripts/redrive-dlq.sh
#
# Use it after fixing the printer (labels, cover): requests that failed 5 times wait in the DLQ.
# SQS moves them back to the queue they came from within about a minute; the print laptop then
# prints them. Run queue-status.sh to watch the DLQ empty.

set -euo pipefail
source "$(dirname "$0")/common.sh"

# Starts the move.
# Arguments:
#   None.
# Returns:
#   0 after starting the move task.
main() {
  local region dlq_arn task
  load_outputs
  region="$(tf_output aws_region)"
  dlq_arn="$(tf_output print_dlq_arn)"
  task="$(aws sqs start-message-move-task --region "$region" --source-arn "$dlq_arn" --query TaskHandle --output text)"
  printf 'Moving the DLQ back to the print queue (task %s). It takes about a minute: run scripts/queue-status.sh to watch.\n' "$task"
}

main "$@"
