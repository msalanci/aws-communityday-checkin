# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The IAM user of the print laptop: it may only receive and delete print requests on the print queue.
# Its access key is created outside Terraform, with the AWS CLI, so the secret never reaches the state;
# force_destroy lets terraform destroy remove the user together with that key. 
# Temporary credentials made from the key are refused, so deleting the key cuts off every copy of it at once.

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

resource "aws_iam_user" "print_laptop" {
  name          = "${var.name_prefix}-print-laptop"
  force_destroy = true
}

resource "aws_iam_user_policy" "print_laptop" {
  name   = "read-and-delete-print-requests"
  user   = aws_iam_user.print_laptop.name
  policy = data.aws_iam_policy_document.print_laptop.json
}
