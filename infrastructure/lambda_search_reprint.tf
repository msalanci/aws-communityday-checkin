# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The search_reprint Lambda behind GET /api/search and POST /api/reprint: its zip (handler.py plus shared/),
# log group, role and function. It reads the SSM parameters, searches pretix and sends print requests.

data "archive_file" "search_reprint" {
  type        = "zip"
  output_path = "${local.build_dir}/search_reprint.zip"

  source {
    content  = file("${local.lambda_dir}/search_reprint/handler.py")
    filename = "handler.py"
  }

  dynamic "source" {
    for_each = fileset("${local.lambda_dir}/shared", "*.py")
    content {
      content  = file("${local.lambda_dir}/shared/${source.value}")
      filename = "shared/${source.value}"
    }
  }
}

data "aws_iam_policy_document" "search_reprint" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.search_reprint.arn}:*"]
  }

  statement {
    sid       = "ReadCheckinParameters"
    actions   = ["ssm:GetParameters"]
    resources = ["arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_prefix}/*"]
  }

  statement {
    sid       = "SendPrintRequests"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.print_requests.arn]
  }
}

resource "aws_cloudwatch_log_group" "search_reprint" {
  name              = "/aws/lambda/${var.name_prefix}-search-reprint"
  retention_in_days = 7
}

resource "aws_iam_role" "search_reprint" {
  name               = "${var.name_prefix}-search-reprint"
  description        = "Role of the search_reprint Lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "search_reprint" {
  name   = "search-reprint"
  role   = aws_iam_role.search_reprint.id
  policy = data.aws_iam_policy_document.search_reprint.json
}

resource "aws_lambda_function" "search_reprint" {
  function_name    = "${var.name_prefix}-search-reprint"
  description      = "GET /api/search and POST /api/reprint: finds attendees and prints another sticker"
  role             = aws_iam_role.search_reprint.arn
  runtime          = "python3.14"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.search_reprint.output_path
  source_code_hash = data.archive_file.search_reprint.output_base64sha256
  memory_size      = 256
  timeout          = 10

  environment {
    variables = {
      SSM_PREFIX       = var.ssm_prefix
      QUEUE_URL        = aws_sqs_queue.print_requests.id
      PRETIX_BASE_URL  = var.pretix_base_url
      EVENT_TIMEZONE   = var.event_timezone
      EVENT_UTC_OFFSET = var.event_utc_offset
    }
  }

  depends_on = [aws_cloudwatch_log_group.search_reprint, aws_iam_role_policy.search_reprint]
}
