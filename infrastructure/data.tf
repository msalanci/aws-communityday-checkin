# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Facts the app stack reads but does not manage: the account, partition and the existing DNS zone.
# Terraform only adds the scanner page's records to that zone; the zone itself is never changed.

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_route53_zone" "parent" {
  name         = var.domain_name
  private_zone = false
}

locals {
  scanner_host = var.subdomain == "" ? var.domain_name : "${var.subdomain}.${var.domain_name}"
  lambda_dir   = "${path.module}/../app/lambda"
  build_dir    = "${path.module}/.build"
}
