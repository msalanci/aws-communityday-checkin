# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""The pretix check-in API, called with urllib.request: redeem a ticket on the check-in list.

pretix answers about a ticket in the JSON's "status", not in the HTTP code (201 for ok, 404 for
an unknown ticket, 400 for most refusals), so any response whose JSON has "status" is an answer.
Everything else is pretix being unavailable, in one of three kinds the phone explains
differently: no_answer, busy, access. The Lambdas never retry pretix themselves, and never follow
a redirect, which would carry the token to another address.
"""

import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from shared.config import Config

TIMEOUT_SECONDS = 4
USER_AGENT = "cd-registration-app"


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect, so a 3xx comes back as an HTTPError instead of being followed."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        """Refuse to follow the redirect.

        Args:
            req: The original request.
            fp: The response body.
            code: The 3xx status.
            msg: The status text.
            headers: The response headers.
            newurl: Where pretix pointed.

        Returns:
            None, which makes urllib raise the 3xx as an HTTPError.
        """
        return None


def open_without_redirects(request: urllib.request.Request, timeout: float) -> Any:
    """Send a request without following redirects.

    Args:
        request: The prepared request.
        timeout: Seconds per network step.

    Returns:
        The response.

    Raises:
        urllib.error.HTTPError: For every status of 300 and above.
        urllib.error.URLError: When pretix cannot be reached.
    """
    return urllib.request.build_opener(NoRedirects).open(request, timeout=timeout)


class PretixUnavailable(Exception):
    """pretix gave no usable answer.

    Attributes:
        kind: "no_answer", "busy" or "access", which decides the phone's message.
        reason: A short word for the log line, such as "timeout" or "http_401".
        http: pretix's HTTP status, or None when there was no response.
    """

    def __init__(self, kind: str, reason: str, http: int | None = None) -> None:
        """Describe the failure.

        Args:
            kind: "no_answer", "busy" or "access".
            reason: The word for the log line.
            http: The HTTP status, if pretix answered.

        Returns:
            None.
        """
        super().__init__(f"{kind}: {reason}")
        self.kind, self.reason, self.http = kind, reason, http


@dataclass(frozen=True)
class PretixAnswer:
    """pretix's answer about a ticket: its HTTP status and the JSON body, which has "status"."""

    http: int
    body: dict[str, Any]


def redeem(
    config: Config,
    base_url: str,
    secret: str,
    nonce: str,
    opener: Callable[..., Any] | None = None,
) -> PretixAnswer:
    """Check a ticket in on the check-in list.

    Args:
        config: The organizer slug, list ID and token.
        base_url: pretix's address, for example "https://pretix.eu".
        secret: The ticket secret, exactly as scanned; pretix accepts untrusted input here.
        nonce: The phone's nonce; the same nonce for the same ticket never checks in twice.
        opener: Sends the request; None opens it without following redirects.

    Returns:
        pretix's answer.

    Raises:
        PretixUnavailable: pretix did not answer about the ticket.
    """
    body = {
        "secret": secret,
        "source_type": "barcode",
        "lists": [config.list_id],
        "type": "entry",
        "nonce": nonce,
        "questions_supported": False,
    }
    request = urllib.request.Request(
        _url(config, base_url, "redeem/"),
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=_headers(config, has_body=True),
    )
    return _call(request, opener or open_without_redirects)


def _url(config: Config, base_url: str, endpoint: str) -> str:
    """Build the address of a checkinrpc endpoint.

    Args:
        config: For the organizer slug.
        base_url: pretix's address.
        endpoint: The endpoint, for example "redeem/".

    Returns:
        The full URL.
    """
    organizer = urllib.parse.quote(config.organizer, safe="")
    return f"{base_url.rstrip('/')}/api/v1/organizers/{organizer}/checkinrpc/{endpoint}"


def _headers(config: Config, has_body: bool) -> dict[str, str]:
    """Build the request headers.

    Args:
        config: For the token.
        has_body: Whether the request sends JSON.

    Returns:
        The headers.
    """
    headers = {"Authorization": f"Token {config.token}", "Accept": "application/json", "User-Agent": USER_AGENT}
    if has_body:
        headers["Content-Type"] = "application/json"
    return headers


def _call(request: urllib.request.Request, opener: Callable[..., Any]) -> PretixAnswer:
    """Send a request and sort pretix's response into an answer or a kind of unavailability.

    Args:
        request: The prepared request.
        opener: Sends it.

    Returns:
        The answer, when the JSON body has "status".

    Raises:
        PretixUnavailable: Timeout, connection error, a broken or cut-off response, a redirect, 5xx,
            a body that is not JSON, a 4xx without "status" (wrong token, organizer or list), 429,
            or a 2xx without "status".
    """
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        try:
            raw = error.read()
        except (OSError, http.client.HTTPException):
            raw = b""
    except (TimeoutError, socket.timeout):
        raise PretixUnavailable("no_answer", "timeout") from None
    except urllib.error.URLError as error:
        reason = "timeout" if isinstance(error.reason, (TimeoutError, socket.timeout)) else "connection"
        raise PretixUnavailable("no_answer", reason) from None
    except (OSError, http.client.HTTPException):
        raise PretixUnavailable("no_answer", "broken_response") from None
    if 300 <= status < 400:
        raise PretixUnavailable("no_answer", f"redirect_{status}", status)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        data = None
    if isinstance(data, dict) and "status" in data:
        return PretixAnswer(status, data)
    if status == 429:
        raise PretixUnavailable("busy", "http_429", status)
    if 400 <= status < 500:
        raise PretixUnavailable("access", f"http_{status}", status)
    if status >= 500:
        raise PretixUnavailable("no_answer", f"http_{status}", status)
    raise PretixUnavailable("no_answer", "no_status" if data is not None else "not_json", status)
