# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The scanner page's custom domain on the HTTP API, mapped to its stage, and its alias record in the zone.

resource "aws_apigatewayv2_domain_name" "scanner" {
  domain_name = local.scanner_host

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.scanner.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "scanner" {
  api_id      = aws_apigatewayv2_api.checkin.id
  domain_name = aws_apigatewayv2_domain_name.scanner.id
  stage       = aws_apigatewayv2_stage.default.id
}

resource "aws_route53_record" "scanner" {
  zone_id = data.aws_route53_zone.parent.zone_id
  name    = local.scanner_host
  type    = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.scanner.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.scanner.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}
