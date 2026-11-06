# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""The gate of every /api/ route: the settings from SSM, then the X-Staff-Pin header against the staff PIN."""

import hmac
from typing import Any

from shared import config, outcomes
from shared.responses import respond


def pin_ok(headers: dict[str, Any] | None, staff_pin: str) -> bool:
    """Compare the request's staff PIN with the real one in constant time.

    Args:
        headers: The request headers; API Gateway's payload 2.0 sends their names in lowercase.
        staff_pin: The staff PIN from SSM.

    Returns:
        True only when the header is present and equals the PIN.
    """
    given = (headers or {}).get("x-staff-pin")
    if not isinstance(given, str) or not given or not staff_pin:
        return False
    return hmac.compare_digest(given.encode("utf-8"), staff_pin.encode("utf-8"))


def admit(event: dict[str, Any], fields: dict[str, Any]) -> tuple[config.Config | None, tuple[str, dict[str, Any]] | None]:
    """Load the settings and check the staff PIN, before a request is looked at any further.

    Args:
        event: API Gateway's payload 2.0 event.
        fields: The log line's fields; gets reason when the settings cannot be read.

    Returns:
        (settings, None) when the request may go on; (None, (result, response)) with the 503 or
        401 answer otherwise.
    """
    try:
        settings = config.load()
    except config.ConfigMissing as error:
        fields["reason"] = "ssm_unreadable" if str(error).startswith("SSM could not") else "config_missing"
        return None, ("unavailable", respond(503, "unavailable", outcomes.UNAVAILABLE["access"]))
    if not pin_ok(event.get("headers"), settings.staff_pin):
        return None, ("unauthorized", respond(401, "unauthorized", outcomes.UNAUTHORIZED))
    return settings, None
