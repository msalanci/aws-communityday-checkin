# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# What the bootstrap hands on: the state bucket's name for the app stack's backend.hcl.

output "state_bucket_name" {
  description = "Name of the S3 bucket for the app stack's state; goes into the app stack's backend.hcl."
  value       = aws_s3_bucket.state.bucket
}
