# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The two Lambdas behind the HTTP API, each with its own zip, log group and function. web serves the
# scanner page's files (handler.py plus the page under static/) and may only write its own logs.
# Scan_reprint, behind every /api/ route, packs handler.py and its modules, reads the SSM parameters, 
# calls pretix and sends print requests.

locals {
  lambda_dir = "${path.module}/../app/lambda"
  build_dir  = "${path.module}/.build"
  web_files  = ["index.html", "app.js", "styles.css", "vendor/html5-qrcode.min.js"]
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
      content  = file("${local.lambda_dir}/web/static/${source.value}")
      filename = "static/${source.value}"
    }
  }
}

data "archive_file" "scan_reprint" {
  type        = "zip"
  output_path = "${local.build_dir}/scan_reprint.zip"

  dynamic "source" {
    for_each = fileset("${local.lambda_dir}/scan_reprint", "*.py")
    content {
      content  = file("${local.lambda_dir}/scan_reprint/${source.value}")
      filename = source.value
    }
  }
}

resource "aws_cloudwatch_log_group" "web" {
  name              = "/aws/lambda/${var.name_prefix}-web"
  retention_in_days = 7
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
      SSM_PREFIX      = var.ssm_prefix
      QUEUE_URL       = aws_sqs_queue.print_requests.id
      PRETIX_BASE_URL = var.pretix_base_url
      EVENT_TIMEZONE  = var.event_timezone
    }
  }

  depends_on = [aws_cloudwatch_log_group.scan_reprint, aws_iam_role_policy.scan_reprint]
}
