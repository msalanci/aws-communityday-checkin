# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The HTTP API that serves the scanner page and its API: its stage, throttle and access log, the TLS certificate
# validated through DNS, its custom domain with the alias record, and the routes to the two Lambdas. 
# The default execute-api address is disabled, so the custom domain is the only way in. 
# A regional custom domain needs its certificate in its own region. 
# The DNS zone already exists: Terraform only adds records to it, never changes it.
# Each integration waits for its function's invoke permission, so API Gateway never calls a function it may not.

locals {
  scanner_host = var.subdomain == "" ? var.domain_name : "${var.subdomain}.${var.domain_name}"
}

data "aws_route53_zone" "parent" {
  name         = var.domain_name
  private_zone = false
}

resource "aws_apigatewayv2_api" "checkin" {
  name                         = "${var.name_prefix}-api"
  description                  = "Scanner page and its API"
  protocol_type                = "HTTP"
  disable_execute_api_endpoint = true
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${var.name_prefix}"
  retention_in_days = 7
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.checkin.id
  name        = "$default"
  description = "The only stage: throttled, with an access log"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
    # Emergency limit if someone floods the API: delete the two lines above, uncomment these two, terraform apply.
    # throttling_burst_limit = 20
    # throttling_rate_limit  = 5
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId = "$context.requestId"
      sourceIp  = "$context.identity.sourceIp"
      routeKey  = "$context.routeKey"
      status    = "$context.status"
      latencyMs = "$context.responseLatency"
    })
  }
}

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

resource "aws_lambda_permission" "api_invokes_web_routes" {
  statement_id  = "ApiInvokesWeb"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.web.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.checkin.execution_arn}/*/GET/*"
}

resource "aws_apigatewayv2_integration" "web" {
  api_id                 = aws_apigatewayv2_api.checkin.id
  description            = "web Lambda"
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.web.invoke_arn
  payload_format_version = "2.0"

  depends_on = [aws_lambda_permission.api_invokes_web_routes]
}

resource "aws_apigatewayv2_route" "web" {
  for_each = toset(["GET /", "GET /app.js", "GET /styles.css", "GET /vendor/{file}"])

  api_id    = aws_apigatewayv2_api.checkin.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.web.id}"
}

resource "aws_lambda_permission" "api_invokes_scan-print_routes" {
  statement_id  = "ApiInvokesScanPrint"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scan-print.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.checkin.execution_arn}/*/*/api/*"
}

resource "aws_apigatewayv2_integration" "scan-print" {
  api_id                 = aws_apigatewayv2_api.checkin.id
  description            = "scan-print Lambda"
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.scan-print.invoke_arn
  payload_format_version = "2.0"

  depends_on = [aws_lambda_permission.api_invokes_scan-print_routes]
}

resource "aws_apigatewayv2_route" "scan-print" {
  for_each = toset(["POST /api/scan", "GET /api/search", "POST /api/reprint"])

  api_id    = aws_apigatewayv2_api.checkin.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.scan-print.id}"
}
