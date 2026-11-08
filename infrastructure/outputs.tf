# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# What the app stack hands on: the print queue for the print laptop's .env, and the names that the operator's AWS CLI commands need.

output "print_queue_url" {
  description = "URL of the print queue; goes into QUEUE_URL in the print laptop's .env."
  value       = aws_sqs_queue.print_requests.id
}

output "print_queue_arn" {
  description = "ARN of the print queue."
  value       = aws_sqs_queue.print_requests.arn
}

output "print_dlq_url" {
  description = "URL of the print queue's dead-letter queue."
  value       = aws_sqs_queue.print_requests_dlq.id
}

output "print_dlq_arn" {
  description = "ARN of the dead-letter queue, the source when moving its messages back."
  value       = aws_sqs_queue.print_requests_dlq.arn
}

output "print_laptop_user_name" {
  description = "Name of the print laptop's IAM user, whose access key the laptop uses."
  value       = aws_iam_user.print_laptop.name
}

output "aws_region" {
  description = "Region of the app stack, for the scripts."
  value       = var.aws_region
}

output "scanner_url" {
  description = "Address of the scanner page and its API."
  value       = "https://${aws_apigatewayv2_domain_name.scanner.domain_name}"
}

output "ssm_prefix" {
  description = "Prefix of the SSM parameters, for the scripts that set them."
  value       = var.ssm_prefix
}

output "api_id" {
  description = "ID of the HTTP API."
  value       = aws_apigatewayv2_api.checkin.id
}

output "project_tag" {
  description = "Value of the project tag, which the scripts put on the parameters they create."
  value       = var.project_tag
}
