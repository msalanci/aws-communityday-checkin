# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The TLS certificate of the scanner page's domain, in the app's own region, validated through DNS
# records in the existing zone. A regional API Gateway custom domain needs its certificate in its region.

resource "aws_acm_certificate" "scanner" {
  domain_name       = local.scanner_host
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.scanner.domain_validation_options : option.domain_name => {
      name   = option.resource_record_name
      type   = option.resource_record_type
      record = option.resource_record_value
    }
  }

  zone_id         = data.aws_route53_zone.parent.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 300
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "scanner" {
  certificate_arn         = aws_acm_certificate.scanner.arn
  validation_record_fqdns = [for record in aws_route53_record.certificate_validation : record.fqdn]
}
