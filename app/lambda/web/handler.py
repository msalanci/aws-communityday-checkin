# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""The web Lambda, behind GET /, /app.js, /styles.css and /vendor/{file}: serves the scanner page's files.

Each path maps to one file under static/ in the function's zip, from a fixed list, so nothing from
the request is ever joined to a file path; anything else is 404. Every response carries the page's
security headers. No environment variables, no PIN, no SSM, no pretix.
"""

import json
import pathlib
import time
from typing import Any

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/vendor/html5-qrcode.min.js": ("vendor/html5-qrcode.min.js", "text/javascript; charset=utf-8"),
}
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(self)",
    "Cache-Control": "no-cache",
}


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Serve one of the page's files.

    Args:
        event: API Gateway's payload 2.0 event; rawPath is the requested path.
        _context: The Lambda context.

    Returns:
        The file with its content type and the security headers, or a plain 404.
    """
    started = time.monotonic()
    path = event.get("rawPath") or "/"
    entry = FILES.get(path)
    if entry is None:
        response = respond(404, "text/plain; charset=utf-8", "Not found")
    else:
        filename, content_type = entry
        response = respond(200, content_type, (STATIC_DIR / filename).read_text(encoding="utf-8"))
    line = {"route": event.get("routeKey", ""), "status": response["statusCode"], "duration_ms": int((time.monotonic() - started) * 1000)}
    print(json.dumps(line), flush=True)
    return response


def respond(status: int, content_type: str, body: str) -> dict[str, Any]:
    """Build a response with the security headers.

    Args:
        status: The HTTP status.
        content_type: The Content-Type header.
        body: The text to send.

    Returns:
        The response for API Gateway.
    """
    return {"statusCode": status, "headers": {"Content-Type": content_type, **SECURITY_HEADERS}, "body": body, "isBase64Encoded": False}
