# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""Checks of what the phone sends: the secret-and-nonce body of a scan or reprint, and the search text."""

import base64
import json
import re
from typing import Any

MAX_SECRET = 200
MIN_QUERY = 3
MAX_QUERY = 100
NONCE_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def read_ticket_body(event: dict[str, Any]) -> tuple[str, str] | None:
    """Read and check the body of a scan or reprint request.

    Args:
        event: API Gateway's payload 2.0 event.

    Returns:
        (secret, nonce), or None when the body is not JSON, the secret is missing, empty or not
        text, or the nonce is not a UUID. A secret over MAX_SECRET characters is returned as it
        is; the caller answers it with "invalid".
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


def read_query(event: dict[str, Any]) -> str | None:
    """Read and check the search text from the query string.

    Args:
        event: API Gateway's payload 2.0 event; queryStringParameters holds q, already decoded.

    Returns:
        The text with runs of spaces collapsed to one and trimmed, or None when it is missing or
        not MIN_QUERY to MAX_QUERY characters long.
    """
    value = (event.get("queryStringParameters") or {}).get("q")
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text if MIN_QUERY <= len(text) <= MAX_QUERY else None
