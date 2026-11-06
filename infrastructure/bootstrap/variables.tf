# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Inputs of the bootstrap: the state bucket's name, its region and the project tag.

variable "state_bucket_name" {
  type        = string
  description = "Name of the S3 bucket that holds the app stack's Terraform state; bucket names are global, so it has no default."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "The state bucket name must be 3-63 lowercase letters, digits, dots or hyphens."
  }
}

variable "aws_region" {
  type        = string
  description = "AWS region of the state bucket."
  default     = "eu-central-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]$", var.aws_region))
    error_message = "The region must look like eu-central-1."
  }
}

variable "project_tag" {
  type        = string
  description = "Value of the project tag on every resource."
  default     = "cd-registration-app"

  validation {
    condition     = length(var.project_tag) > 0
    error_message = "The project tag must not be empty."
  }
}
