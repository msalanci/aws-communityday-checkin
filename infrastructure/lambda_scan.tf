# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The scan Lambda behind POST /api/scan: its zip (handler.py plus shared/), log group, role and function.
# It reads the SSM parameters, calls pretix and sends print requests to the print queue.

data "archive_file" "scan" {
  type        = "zip"
  output_path = "${local.build_dir}/scan.zip"

  source {
    content  = file("${local.lambda_dir}/scan/handler.py")
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

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    sid     = "LambdaAssumesRole"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "scan" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.scan.arn}:*"]
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

resource "aws_cloudwatch_log_group" "scan" {
  name              = "/aws/lambda/${var.name_prefix}-scan"
  retention_in_days = 7
}

resource "aws_iam_role" "scan" {
  name               = "${var.name_prefix}-scan"
  description        = "Role of the scan Lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "scan" {
  name   = "scan"
  role   = aws_iam_role.scan.id
  policy = data.aws_iam_policy_document.scan.json
}

resource "aws_lambda_function" "scan" {
  function_name    = "${var.name_prefix}-scan"
  description      = "POST /api/scan: checks a ticket in at pretix and sends its print request"
  role             = aws_iam_role.scan.arn
  runtime          = "python3.14"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.scan.output_path
  source_code_hash = data.archive_file.scan.output_base64sha256
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

  depends_on = [aws_cloudwatch_log_group.scan, aws_iam_role_policy.scan]
}
