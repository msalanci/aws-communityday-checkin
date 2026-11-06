# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""The staff PIN check of every /api/ route: the X-Staff-Pin header against the PIN from SSM."""

import hmac
from typing import Any


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
