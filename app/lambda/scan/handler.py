# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""The scan Lambda, behind POST /api/scan: checks a ticket in at pretix and sends its print request.

The phone sends the scanned text and a nonce; this function checks the staff PIN, redeems the
ticket on the check-in list with that nonce, and for a valid ticket with a name puts a print
request on the print queue. Environment: SSM_PREFIX, QUEUE_URL, PRETIX_BASE_URL, EVENT_TIMEZONE,
EVENT_UTC_OFFSET. Every outcome about a ticket is HTTP 200 with "result" and "message".
"""

import base64
import json
import re
import time
from typing import Any

from shared import auth, config, logs, names, outcomes, pretix, print_queue
from shared.responses import attendee, respond

ROUTE = "POST /api/scan"
MAX_SECRET = 200
NONCE_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Handle one scan.

    Args:
        event: API Gateway's payload 2.0 event.
        _context: The Lambda context.

    Returns:
        The API Gateway response; an unexpected error is a 500 with the generic message.
    """
    started = time.monotonic()
    fields: dict[str, Any] = {}
    try:
        result, response = scan(event, fields)
    except Exception as error:
        fields["error"] = logs.where(error)
        result, response = "error", respond(500, "error", outcomes.ERROR)
    logs.write(ROUTE, result, started, fields)
    return response


def read_body(event: dict[str, Any]) -> tuple[str, str] | None:
    """Read and check the request body.

    Args:
        event: API Gateway's event.

    Returns:
        (secret, nonce), or None when the body is not JSON, the secret is missing, empty or not
        text, or the nonce is not a UUID.
    """
    raw = event.get("body") or ""
    try:
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    secret, nonce = data.get("secret"), data.get("nonce")
    if not isinstance(secret, str) or not secret or not isinstance(nonce, str) or not NONCE_PATTERN.fullmatch(nonce):
        return None
    return secret, nonce


def scan(event: dict[str, Any], fields: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Do the scan's work.

    Args:
        event: API Gateway's event.
        fields: Filled with the log line's fields.

    Returns:
        (result, response).
    """
    try:
        settings = config.load()
    except config.ConfigMissing as error:
        fields["reason"] = "ssm_unreadable" if str(error).startswith("SSM could not") else "config_missing"
        return "unavailable", respond(503, "unavailable", outcomes.UNAVAILABLE["access"])
    if not auth.pin_ok(event.get("headers"), settings.staff_pin):
        return "unauthorized", respond(401, "unauthorized", outcomes.UNAUTHORIZED)
    request = read_body(event)
    if request is None:
        return "bad_request", respond(400, "bad_request", outcomes.BAD_REQUEST)
    secret, nonce = request
    if len(secret) > MAX_SECRET:
        fields["reason"] = "secret_too_long"
        return "invalid", respond(200, "invalid", outcomes.INVALID)
    try:
        answer = pretix.redeem(settings, config.env("PRETIX_BASE_URL", "https://pretix.eu"), secret, nonce)
    except pretix.PretixUnavailable as error:
        fields.update(reason=error.reason, pretix_http=error.http)
        return "unavailable", respond(503, "unavailable", outcomes.UNAVAILABLE[error.kind])
    fields["pretix_http"] = answer.http
    reading = outcomes.read_answer(answer.body)
    fields["reason"] = reading.reason
    position = answer.body.get("position") if isinstance(answer.body.get("position"), dict) else {}
    order_code = position.get("order") if isinstance(position.get("order"), str) else ""
    fields["order_code"] = order_code
    if reading.kind == "refused":
        return "invalid", respond(200, "invalid", outcomes.INVALID)
    first_name, last_name = names.name_from(position)
    if not first_name and not last_name:
        fields["reason"] = "no_name"
        return "invalid", respond(200, "invalid", outcomes.INVALID)
    person = attendee(first_name, last_name, order_code)
    if reading.kind == "already":
        return already_checked_in(position, person, fields)
    request_id = print_queue.print_id(nonce, secret)
    fields["print_id"] = request_id
    if not print_queue.send(config.aws_client("sqs"), config.env("QUEUE_URL"), request_id, first_name, last_name):
        fields["reason"] = "sqs_failed"
        return "print_failed", respond(200, "print_failed", outcomes.SCAN_PRINT_FAILED, attendee=person)
    name = names.full_name(first_name, last_name)
    return "checked_in", respond(200, "checked_in", outcomes.CHECKED_IN.format(name=name), attendee=person)


def already_checked_in(position: dict[str, Any], person: dict[str, str], fields: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Answer for a ticket that was checked in before, with the time of its latest entry.

    Args:
        position: The position from pretix's answer.
        person: The attendee object.
        fields: The log line's fields; gets time_zone when the event's zone was not found.

    Returns:
        (result, response).
    """
    zone, how = outcomes.event_zone(config.env("EVENT_TIMEZONE", "Europe/Bratislava"), config.env("EVENT_UTC_OFFSET"))
    if how != "zoneinfo":
        fields["time_zone"] = how
    moment = outcomes.latest_entry(position, zone)
    if moment is None:
        return "already_checked_in", respond(
            200, "already_checked_in", outcomes.ALREADY_CHECKED_IN_NO_TIME, attendee=person, checked_in_at=None
        )
    message = outcomes.ALREADY_CHECKED_IN.format(time=moment.strftime("%H:%M"))
    stamp = moment.isoformat(timespec="seconds")
    return "already_checked_in", respond(200, "already_checked_in", message, attendee=person, checked_in_at=stamp)
