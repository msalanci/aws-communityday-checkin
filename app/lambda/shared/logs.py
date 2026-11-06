# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""One JSON log line per request, printed so it lands in CloudWatch as it is.

Only the fields in ALLOWED are ever written: never names, emails, ticket secrets, the search
text, the PIN, the pretix token, request bodies or pretix responses.
"""

import json
import time
from typing import Any

ALLOWED = ("reason", "order_code", "print_id", "pretix_http", "q_length", "time_zone", "error")


def write(route: str, result: str, started: float, fields: dict[str, Any]) -> None:
    """Print the request's log line.

    Args:
        route: The route, for example "POST /api/scan".
        result: The outcome, for example "checked_in".
        started: time.monotonic() when the request started.
        fields: More fields; only those in ALLOWED are written.

    Returns:
        None. Prints one line to stdout, which Lambda sends to CloudWatch.
    """
    line = {"route": route, "result": result, "reason": ""}
    line.update({key: value for key, value in fields.items() if key in ALLOWED and value not in (None, "")})
    line["duration_ms"] = int((time.monotonic() - started) * 1000)
    print(json.dumps(line, ensure_ascii=False), flush=True)


def where(error: BaseException) -> str:
    """Name an unexpected exception for the log line without its message, which may hold data.

    Args:
        error: The exception.

    Returns:
        Its class and the file and line where it was raised, for example "KeyError at handler.py:42".
    """
    traceback = error.__traceback__
    while traceback is not None and traceback.tb_next is not None:
        traceback = traceback.tb_next
    if traceback is None:
        return type(error).__name__
    filename = traceback.tb_frame.f_code.co_filename.rsplit("/", 1)[-1]
    return f"{type(error).__name__} at {filename}:{traceback.tb_lineno}"
