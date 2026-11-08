# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""API Gateway (payload 2.0) responses of the /api/ routes: JSON with "result" and "message"."""

import json
from typing import Any

HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def respond(status: int, result: str, message: str, **fields: Any) -> dict[str, Any]:
    """Build one response.

    Args:
        status: The HTTP status: 200 for anything about a ticket, an error code for technical failures.
        result: The outcome's name, for example "checked_in".
        message: The exact text the phone shows.
        **fields: More body fields, for example attendee or checked_in_at.

    Returns:
        The response for API Gateway.
    """
    body = {"result": result, "message": message, **fields}
    return {"statusCode": status, "headers": dict(HEADERS), "body": json.dumps(body, ensure_ascii=False)}


def attendee(first_name: str, last_name: str, order_code: str) -> dict[str, str]:
    """Build the attendee object of a response.

    Args:
        first_name: The cleaned first name.
        last_name: The cleaned last name.
        order_code: The pretix order code.

    Returns:
        {"first_name", "last_name", "order_code"}.
    """
    return {"first_name": first_name, "last_name": last_name, "order_code": order_code}
