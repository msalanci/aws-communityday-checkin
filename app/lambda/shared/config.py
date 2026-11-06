# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""Settings of the scan and search_reprint Lambdas: environment variables and four SSM parameters.

The SSM parameters (organizer slug, check-in list ID, pretix token, staff PIN) are read with one
GetParameters call and kept in the warm Lambda for 5 minutes, so a new PIN or list applies
within 5 minutes. Also builds the boto3 clients, with short timeouts so every answer reaches the
phone well inside the Lambda's 10 s.
"""

import os
import time
from dataclasses import dataclass
from typing import Any, Callable

CACHE_SECONDS = 300
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
        The client, with 1 s connect and 2 s read timeouts and 3 attempts in standard retry mode.
    """
    if service not in _clients:
        import boto3
        from botocore.config import Config as BotoConfig

        _clients[service] = boto3.client(
            service,
            config=BotoConfig(connect_timeout=1, read_timeout=2, retries={"mode": "standard", "max_attempts": 3}),
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


def forget() -> None:
    """Empty the parameter cache and the clients, so the next call reads SSM again.

    Args:
        None.

    Returns:
        None.
    """
    _cache.update(config=None, loaded_at=float("-inf"))
    _clients.clear()
