# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Every IAM identity of the app and what it may do: a role per Lambda, and the print laptop's IAM user, which
# may only receive and delete print requests. The user's access key is created outside Terraform, with the AWS
# CLI, so the secret never reaches the state; force_destroy lets terraform destroy remove the user with that key.
# Temporary credentials made from the key are refused, so deleting the key cuts off every copy of it at once.

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

data "aws_iam_policy_document" "print_laptop" {
  statement {
    sid = "ReadAndDeletePrintRequests"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
    ]
    resources = [aws_sqs_queue.print_requests.arn]
  }

  statement {
    sid       = "DenyTemporaryCredentials"
    effect    = "Deny"
    actions   = ["sqs:*"]
    resources = ["*"]

    condition {
      test     = "Null"
      variable = "aws:TokenIssueTime"
      values   = ["false"]
    }
  }
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

resource "aws_iam_user" "print_laptop" {
  name          = "${var.name_prefix}-print-laptop"
  force_destroy = true
}

resource "aws_iam_user_policy" "print_laptop" {
  name   = "read-and-delete-print-requests"
  user   = aws_iam_user.print_laptop.name
  policy = data.aws_iam_policy_document.print_laptop.json
}
