# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""Settings of the scan_reprint Lambda: environment variables and four SSM parameters.

The SSM parameters (organizer slug, check-in list ID, pretix token, staff PIN) are read with one
GetParameters call and kept in the warm Lambda for 5 minutes, so a new PIN or list applies
within 5 minutes. Also builds the boto3 clients, with short timeouts, and checks the time left
before each slow step, so every answer reaches the phone inside the Lambda's 10 s.
"""

import os
import time
from dataclasses import dataclass
from typing import Any, Callable

CACHE_SECONDS = 300
PRETIX_BUDGET_MS = 8500
SQS_BUDGET_MS = 2500
PARAMETERS = ("pretix/organizer", "pretix/checkin-list-id", "pretix/token", "staff-pin")
PLACEHOLDER = "set-by-script"

_cache: dict[str, Any] = {"config": None, "loaded_at": float("-inf")}
_clients: dict[str, Any] = {}


class ConfigMissing(Exception):
    """A parameter is missing or not set yet; the message names it, never a value."""


@dataclass(frozen=True)
class Config:
    """The four SSM parameters, read and checked."""

    organizer: str
    list_id: int
    token: str
    staff_pin: str


def env(name: str, default: str = "") -> str:
    """Read an environment variable set by Terraform.

    Args:
        name: The variable's name.
        default: The value when it is unset or empty.

    Returns:
        The value, without surrounding spaces.
    """
    return os.environ.get(name, "").strip() or default


def aws_client(service: str) -> Any:
    """Return a boto3 client, created once per warm Lambda.

    Args:
        service: The AWS service, "ssm" or "sqs".

    Returns:
        The client, with 1 s connect and 1 s read timeouts and 2 attempts in standard retry mode,
        so one call takes at most about 5 s.
    """
    if service not in _clients:
        import boto3
        from botocore.config import Config as BotoConfig

        _clients[service] = boto3.client(
            service,
            config=BotoConfig(connect_timeout=1, read_timeout=1, retries={"mode": "standard", "max_attempts": 2}),
        )
    return _clients[service]


def load(client: Any = None, clock: Callable[[], float] = time.monotonic) -> Config:
    """Return the SSM parameters, from the 5-minute cache or with one GetParameters call.

    Args:
        client: The SSM client; None uses aws_client("ssm").
        clock: Returns a monotonic time in seconds; replaceable in tests.

    Returns:
        The parameters.

    Raises:
        ConfigMissing: SSM could not be read (access, decryption, throttling, no connection), a
            parameter is missing, blank or still holds the Terraform placeholder, or the list ID is
            not a number in ASCII digits.
    """
    from botocore.exceptions import BotoCoreError, ClientError

    now = clock()
    if _cache["config"] is not None and now - _cache["loaded_at"] < CACHE_SECONDS:
        return _cache["config"]
    prefix = env("SSM_PREFIX", "/cd-registration").rstrip("/")
    names = {short: f"{prefix}/{short}" for short in PARAMETERS}
    try:
        answer = (client or aws_client("ssm")).get_parameters(Names=list(names.values()), WithDecryption=True)
    except (BotoCoreError, ClientError) as error:
        raise ConfigMissing(f"SSM could not be read: {type(error).__name__}") from None
    values = {parameter["Name"]: str(parameter.get("Value", "")).strip() for parameter in answer.get("Parameters", [])}
    for full in names.values():
        if not values.get(full) or values[full] == PLACEHOLDER:
            raise ConfigMissing(f"SSM parameter {full} is missing or not set yet")
    list_text = values[names["pretix/checkin-list-id"]]
    if not (list_text.isascii() and list_text.isdigit()):
        raise ConfigMissing(f"SSM parameter {names['pretix/checkin-list-id']} is not a number")
    config = Config(
        organizer=values[names["pretix/organizer"]],
        list_id=int(list_text),
        token=values[names["pretix/token"]],
        staff_pin=values[names["staff-pin"]],
    )
    _cache.update(config=config, loaded_at=now)
    return config


def time_left_ok(context: Any, needed_ms: int) -> bool:
    """Tell whether the Lambda has time left for a slow step.

    A step started too late would be cut off by the Lambda's timeout, and the phone would get
    API Gateway's own error instead of a message that says what to do.

    Args:
        context: The Lambda context; None (in tests) always has time.
        needed_ms: The step's worst case in milliseconds: PRETIX_BUDGET_MS for a pretix call
            (4 s to connect plus 4 s to read), SQS_BUDGET_MS for sending a print request.

    Returns:
        True when at least needed_ms are left.
    """
    if context is None:
        return True
    return context.get_remaining_time_in_millis() >= needed_ms


def forget() -> None:
    """Empty the parameter cache and the clients, so the next call reads SSM again.

    Args:
        None.

    Returns:
        None.
    """
    _cache.update(config=None, loaded_at=float("-inf"))
    _clients.clear()
