# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""The scan Lambda, behind POST /api/scan: checks a ticket in at pretix and sends its print request.

The phone sends the scanned text and a nonce; this function checks the staff PIN, redeems the
ticket on the check-in list with that nonce, and for a valid ticket with a name puts a print
request on the print queue. Environment: SSM_PREFIX, QUEUE_URL, PRETIX_BASE_URL, EVENT_TIMEZONE,
EVENT_UTC_OFFSET. Every outcome about a ticket is HTTP 200 with "result" and "message".
"""

import time
from typing import Any

from shared import auth, config, logs, names, outcomes, pretix, print_queue, validation
from shared.responses import attendee, respond

ROUTE = "POST /api/scan"


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


def scan(event: dict[str, Any], fields: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Do the scan's work.

    Args:
        event: API Gateway's event.
        fields: Filled with the log line's fields.

    Returns:
        (result, response).
    """
    settings, refusal = auth.admit(event, fields)
    if refusal is not None:
        return refusal
    request = validation.read_ticket_body(event)
    if request is None:
        return "bad_request", respond(400, "bad_request", outcomes.BAD_REQUEST)
    secret, nonce = request
    if len(secret) > validation.MAX_SECRET:
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
    moment = outcomes.latest_entry(position, outcomes.zone_from_env(fields))
    if moment is None:
        return "already_checked_in", respond(
            200, "already_checked_in", outcomes.ALREADY_CHECKED_IN_NO_TIME, attendee=person, checked_in_at=None
        )
    message = outcomes.ALREADY_CHECKED_IN.format(time=moment.strftime("%H:%M"))
    stamp = moment.isoformat(timespec="seconds")
    return "already_checked_in", respond(200, "already_checked_in", message, attendee=person, checked_in_at=stamp)
