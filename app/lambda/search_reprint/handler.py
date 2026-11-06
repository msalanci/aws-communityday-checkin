# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""The search_reprint Lambda, behind GET /api/search and POST /api/reprint, chosen by the route key.

Search finds attendees on the check-in list by name or order code, never by email, for a manual
check-in or a reprint from the phone. Reprint prints another sticker for a ticket that is already
checked in, without checking it in again. Environment: SSM_PREFIX, QUEUE_URL, PRETIX_BASE_URL,
EVENT_TIMEZONE, EVENT_UTC_OFFSET.
"""

import time
from typing import Any, Callable

from shared import auth, config, logs, names, outcomes, pretix, print_queue, validation
from shared.responses import attendee, respond

REPRINT_LOOKUP_SIZE = 2


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Handle one search or reprint request.

    Args:
        event: API Gateway's payload 2.0 event; routeKey picks the work.
        _context: The Lambda context.

    Returns:
        The API Gateway response; an unexpected error is a 500 with the generic message.
    """
    started = time.monotonic()
    route = str(event.get("routeKey") or "")
    fields: dict[str, Any] = {}
    work: Callable[[dict[str, Any], dict[str, Any]], tuple[str, dict[str, Any]]] | None = ROUTES.get(route)
    try:
        if work is None:
            result, response = "bad_request", respond(400, "bad_request", outcomes.BAD_REQUEST)
        else:
            result, response = work(event, fields)
    except Exception as error:
        fields["error"] = logs.where(error)
        result, response = "error", respond(500, "error", outcomes.ERROR)
    logs.write(route, result, started, fields)
    return response


def search(event: dict[str, Any], fields: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Search the check-in list and keep only results whose name or order code contains the text.

    pretix also matches order emails and the start of the secret; those results are dropped, so
    the search tab cannot list attendees by email.

    Args:
        event: API Gateway's event, with q in the query string.
        fields: Filled with the log line's fields; the text itself is never logged, only its length.

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


def reprint(event: dict[str, Any], fields: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Print another sticker for a ticket that is checked in; never check it in.

    Args:
        event: API Gateway's event, with the ticket's secret and a new nonce in the body.
        fields: Filled with the log line's fields.

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
    if not print_queue.send(config.aws_client("sqs"), config.env("QUEUE_URL"), request_id, first_name, last_name):
        fields["reason"] = "sqs_failed"
        return "print_failed", respond(200, "print_failed", outcomes.REPRINT_FAILED, attendee=person)
    name = names.full_name(first_name, last_name)
    return "reprinting", respond(200, "reprinting", outcomes.REPRINTING.format(name=name), attendee=person)


ROUTES: dict[str, Callable[[dict[str, Any], dict[str, Any]], tuple[str, dict[str, Any]]]] = {
    "GET /api/search": search,
    "POST /api/reprint": reprint,
}
