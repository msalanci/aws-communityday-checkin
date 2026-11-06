# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The HTTP API that serves the scanner page and its API under one custom domain, with its stage, throttle
# and access log. The default execute-api address is disabled, so the custom domain is the only way in.

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

resource "aws_apigatewayv2_integration" "scan" {
  api_id                 = aws_apigatewayv2_api.checkin.id
  description            = "scan Lambda"
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.scan.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "scan" {
  api_id    = aws_apigatewayv2_api.checkin.id
  route_key = "POST /api/scan"
  target    = "integrations/${aws_apigatewayv2_integration.scan.id}"
}

resource "aws_lambda_permission" "api_invokes_scan" {
  statement_id  = "ApiInvokesScan"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scan.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.checkin.execution_arn}/*/POST/api/scan"
}

resource "aws_apigatewayv2_integration" "web" {
  api_id                 = aws_apigatewayv2_api.checkin.id
  description            = "web Lambda"
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.web.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "web" {
  for_each = toset(["GET /", "GET /app.js", "GET /styles.css", "GET /vendor/{file}"])

  api_id    = aws_apigatewayv2_api.checkin.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.web.id}"
}

resource "aws_lambda_permission" "api_invokes_web" {
  for_each = {
    root   = "/*/GET/"
    script = "/*/GET/app.js"
    styles = "/*/GET/styles.css"
    vendor = "/*/GET/vendor/*"
  }

  statement_id  = "ApiInvokesWeb-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.web.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.checkin.execution_arn}${each.value}"
}
