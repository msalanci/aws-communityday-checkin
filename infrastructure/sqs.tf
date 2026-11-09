# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The print queue that carries print requests to the print laptop, and its dead-letter queue.
# A print request moves to the DLQ after 5 unconfirmed prints. 
# The DLQ keeps messages longer than the queue, because a moved message keeps its original age; 
# both keep names only briefly.

resource "aws_sqs_queue" "print_requests_dlq" {
  name                      = "${var.name_prefix}-print-requests-dlq"
  message_retention_seconds = 172800
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "print_requests" {
  name                       = "${var.name_prefix}-print-requests"
  message_retention_seconds  = 86400
  visibility_timeout_seconds = 60
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
}

resource "aws_sqs_queue_redrive_policy" "print_requests" {
  queue_url = aws_sqs_queue.print_requests.id
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.print_requests_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "print_requests_dlq" {
  queue_url = aws_sqs_queue.print_requests_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.print_requests.arn]
  })
}
