# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Terraform and provider versions for the app stack, with its state in the bootstrap's S3 bucket.
# The backend's bucket, key and region come from backend.hcl (terraform init -backend-config=backend.hcl);
# S3 native lock files replace a DynamoDB lock table.

terraform {
  required_version = "~> 1.17"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.8"
    }
  }

  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      project   = var.project_tag
      terraform = "yes"
    }
  }
}
