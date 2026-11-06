# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The web Lambda that serves the scanner page: its zip (handler.py plus the page's files under static/),
# log group, role and function. It reads nothing else and may only write its own logs.

locals {
  web_files = ["index.html", "app.js", "styles.css", "vendor/html5-qrcode.min.js"]
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

data "aws_iam_policy_document" "web" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.web.arn}:*"]
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
