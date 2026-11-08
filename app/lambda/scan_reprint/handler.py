# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""The scan_reprint Lambda, behind every /api/ route, which the route key chooses.

POST /api/scan checks a ticket in at pretix and, for a valid ticket with a name, puts a print
request on the print queue. GET /api/search finds attendees on the check-in list by name or order
code, never by email, for a manual check-in or a reprint. POST /api/reprint prints another sticker
for a ticket that is already checked in, without checking it in again. Every route checks the
staff PIN first. Environment: SSM_PREFIX, QUEUE_URL, PRETIX_BASE_URL, EVENT_TIMEZONE,
EVENT_UTC_OFFSET. Every outcome about a ticket is HTTP 200 with "result" and "message".
"""

import time
from typing import Any, Callable

from shared import auth, config, logs, names, outcomes, pretix, print_queue, validation
from shared.responses import attendee, respond

REPRINT_LOOKUP_SIZE = 2


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle one API request: a scan, a search or a reprint.

    Args:
        event: API Gateway's payload 2.0 event; routeKey picks the work.
        context: The Lambda context, for the time left.

    Returns:
        The API Gateway response; an unknown route is a 400, an unexpected error a 500 with the
        generic message.
    """
    started = time.monotonic()
    route = str(event.get("routeKey") or "")
    fields: dict[str, Any] = {}
    work: Callable[[dict[str, Any], dict[str, Any], Any], tuple[str, dict[str, Any]]] | None = ROUTES.get(route)
    try:
        if work is None:
            result, response = "bad_request", respond(400, "bad_request", outcomes.BAD_REQUEST)
        else:
            result, response = work(event, fields, context)
    except Exception as error:
        fields["error"] = logs.where(error)
        result, response = "error", respond(500, "error", outcomes.ERROR)
    logs.write(route, result, started, fields)
    return response


def scan(event: dict[str, Any], fields: dict[str, Any], context: Any = None) -> tuple[str, dict[str, Any]]:
    """Check a scanned ticket in and send its print request.

    Args:
        event: API Gateway's event, with the scanned text and a nonce in the body.
        fields: Filled with the log line's fields.
        context: The Lambda context; with too little time left, pretix is not called (the phone
            gets "pretix did not answer — try again") or the print request is not sent (the phone
            gets "tap Reprint"), instead of being cut off by the timeout.

    Returns:
        (result, response): checked_in, already_checked_in, invalid or print_failed.
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
    if not config.time_left_ok(context, config.PRETIX_BUDGET_MS):
        fields["reason"] = "no_time"
        return "unavailable", respond(503, "unavailable", outcomes.UNAVAILABLE["no_answer"])
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
    if not config.time_left_ok(context, config.SQS_BUDGET_MS):
        fields["reason"] = "no_time"
        return "print_failed", respond(200, "print_failed", outcomes.SCAN_PRINT_FAILED, attendee=person)
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


def search(event: dict[str, Any], fields: dict[str, Any], context: Any = None) -> tuple[str, dict[str, Any]]:
    """Search the check-in list and keep only results whose name or order code contains the text.

    pretix also matches order emails and the start of the secret; those results are dropped, so
    the search tab cannot list attendees by email.

    Args:
        event: API Gateway's event, with q in the query string.
        fields: Filled with the log line's fields; the text itself is never logged, only its length.
        context: The Lambda context; with too little time left, pretix is not called.

    Returns:
        (result, response): "ok" with up to 50 results and whether pretix had more.
    """
    settings, refusal = auth.admit(event, fields)
    if refusal is not None:
        return refusal
    text = validation.read_query(event)
    if text is None:
        return "bad_request", respond(400, "bad_request", outcomes.BAD_REQUEST)
    fields["q_length"] = len(text)
    if not config.time_left_ok(context, config.PRETIX_BUDGET_MS):
        fields["reason"] = "no_time"
        return "unavailable", respond(503, "unavailable", outcomes.UNAVAILABLE["no_answer"])
    try:
        page = pretix.search(settings, config.env("PRETIX_BASE_URL", "https://pretix.eu"), text)
    except pretix.PretixUnavailable as error:
        fields.update(reason=error.reason, pretix_http=error.http)
        return "unavailable", respond(503, "unavailable", outcomes.UNAVAILABLE[error.kind])
    fields["pretix_http"] = page.http
    zone = outcomes.zone_from_env(fields)
    wanted = names.fold(text)
    results = []
    for position in page.results:
        if not isinstance(position, dict) or not isinstance(position.get("secret"), str) or not position["secret"]:
            continue
        first_name, last_name = names.name_from(position)
        order_code = position.get("order") if isinstance(position.get("order"), str) else ""
        if wanted not in names.fold(names.full_name(first_name, last_name)) and wanted not in names.fold(order_code):
            continue
        moment = outcomes.latest_entry(position, zone)
        results.append(
            {
                "secret": position["secret"],
                "first_name": first_name,
                "last_name": last_name,
                "order_code": order_code,
                "checked_in_at": moment.isoformat(timespec="seconds") if moment else None,
            }
        )
    return "ok", respond(200, "ok", "", results=results, more=page.more)


def reprint(event: dict[str, Any], fields: dict[str, Any], context: Any = None) -> tuple[str, dict[str, Any]]:
    """Print another sticker for a ticket that is checked in; never check it in.

    Args:
        event: API Gateway's event, with the ticket's secret and a new nonce in the body.
        fields: Filled with the log line's fields.
        context: The Lambda context; with too little time left, pretix is not called or the print
            request is not sent.

    Returns:
        (result, response): reprinting, not_checked_in, invalid or print_failed.
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
    if not config.time_left_ok(context, config.PRETIX_BUDGET_MS):
        fields["reason"] = "no_time"
        return "unavailable", respond(503, "unavailable", outcomes.UNAVAILABLE["no_answer"])
    try:
        page = pretix.search(
            settings, config.env("PRETIX_BASE_URL", "https://pretix.eu"), secret, page_size=REPRINT_LOOKUP_SIZE, secret=secret
        )
    except pretix.PretixUnavailable as error:
        fields.update(reason=error.reason, pretix_http=error.http)
        return "unavailable", respond(503, "unavailable", outcomes.UNAVAILABLE[error.kind])
    fields["pretix_http"] = page.http
    matches = [position for position in page.results if isinstance(position, dict) and position.get("secret") == secret]
    if len(matches) != 1:
        fields["reason"] = "not_found"
        return "invalid", respond(200, "invalid", outcomes.INVALID)
    position = matches[0]
    order_code = position.get("order") if isinstance(position.get("order"), str) else ""
    fields["order_code"] = order_code
    first_name, last_name = names.name_from(position)
    if not first_name and not last_name:
        fields["reason"] = "no_name"
        return "invalid", respond(200, "invalid", outcomes.INVALID)
    person = attendee(first_name, last_name, order_code)
    if outcomes.latest_entry(position, outcomes.zone_from_env(fields)) is None:
        return "not_checked_in", respond(200, "not_checked_in", outcomes.NOT_CHECKED_IN, attendee=person)
    request_id = print_queue.print_id(nonce, secret)
    fields["print_id"] = request_id
    if not config.time_left_ok(context, config.SQS_BUDGET_MS):
        fields["reason"] = "no_time"
        return "print_failed", respond(200, "print_failed", outcomes.REPRINT_FAILED, attendee=person)
    if not print_queue.send(config.aws_client("sqs"), config.env("QUEUE_URL"), request_id, first_name, last_name):
        fields["reason"] = "sqs_failed"
        return "print_failed", respond(200, "print_failed", outcomes.REPRINT_FAILED, attendee=person)
    name = names.full_name(first_name, last_name)
    return "reprinting", respond(200, "reprinting", outcomes.REPRINTING.format(name=name), attendee=person)


ROUTES: dict[str, Callable[[dict[str, Any], dict[str, Any], Any], tuple[str, dict[str, Any]]]] = {
    "POST /api/scan": scan,
    "GET /api/search": search,
    "POST /api/reprint": reprint,
}
