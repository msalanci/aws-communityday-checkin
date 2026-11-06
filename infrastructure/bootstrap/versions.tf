# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Terraform and provider versions for the bootstrap, which creates the app stack's state bucket.
# Applied once, before the app stack; its own state is a local file whose path comes from backend.hcl.

terraform {
  required_version = "~> 1.17"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72"
    }
  }

  backend "local" {}
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
