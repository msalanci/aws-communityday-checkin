# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The two Lambdas behind the HTTP API, each with its own zip, log group, role and function. web serves the
# scanner page's files (handler.py plus the page under static/) and may only write its own logs. scan_reprint,
# behind every /api/ route, packs handler.py plus shared/, reads the SSM parameters, calls pretix and sends
# print requests.

locals {
  lambda_dir = "${path.module}/../app/lambda"
  build_dir  = "${path.module}/.build"
  web_files  = ["index.html", "app.js", "styles.css", "vendor/html5-qrcode.min.js"]
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

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

data "archive_file" "web" {
  type        = "zip"
  output_path = "${local.build_dir}/web.zip"

  source {
    content  = file("${local.lambda_dir}/web/handler.py")
    filename = "handler.py"
  }

  dynamic "source" {
    for_each = toset(local.web_files)
    content {
      content  = file("${path.module}/../app/web/${source.value}")
      filename = "static/${source.value}"
    }
  }
}

data "archive_file" "scan_reprint" {
  type        = "zip"
  output_path = "${local.build_dir}/scan_reprint.zip"

  source {
    content  = file("${local.lambda_dir}/scan_reprint/handler.py")
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

data "aws_iam_policy_document" "web" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.web.arn}:*"]
  }
}

data "aws_iam_policy_document" "scan_reprint" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.scan_reprint.arn}:*"]
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

resource "aws_cloudwatch_log_group" "web" {
  name              = "/aws/lambda/${var.name_prefix}-web"
  retention_in_days = 7
}

resource "aws_iam_role" "web" {
  name               = "${var.name_prefix}-web"
  description        = "Role of the web Lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "web" {
  name   = "web"
  role   = aws_iam_role.web.id
  policy = data.aws_iam_policy_document.web.json
}

resource "aws_lambda_function" "web" {
  function_name    = "${var.name_prefix}-web"
  description      = "Serves the scanner page's files with their security headers"
  role             = aws_iam_role.web.arn
  runtime          = "python3.14"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.web.output_path
  source_code_hash = data.archive_file.web.output_base64sha256
  memory_size      = 128
  timeout          = 3

  depends_on = [aws_cloudwatch_log_group.web, aws_iam_role_policy.web]
}

resource "aws_cloudwatch_log_group" "scan_reprint" {
  name              = "/aws/lambda/${var.name_prefix}-scan-reprint"
  retention_in_days = 7
}

resource "aws_iam_role" "scan_reprint" {
  name               = "${var.name_prefix}-scan-reprint"
  description        = "Role of the scan_reprint Lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "scan_reprint" {
  name   = "scan-reprint"
  role   = aws_iam_role.scan_reprint.id
  policy = data.aws_iam_policy_document.scan_reprint.json
}

resource "aws_lambda_function" "scan_reprint" {
  function_name    = "${var.name_prefix}-scan-reprint"
  description      = "Every /api/ route: POST /api/scan, GET /api/search and POST /api/reprint"
  role             = aws_iam_role.scan_reprint.arn
  runtime          = "python3.14"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.scan_reprint.output_path
  source_code_hash = data.archive_file.scan_reprint.output_base64sha256
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

  depends_on = [aws_cloudwatch_log_group.scan_reprint, aws_iam_role_policy.scan_reprint]
}
