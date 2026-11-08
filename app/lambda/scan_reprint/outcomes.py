# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""What a pretix answer means for the phone, and every message text the phone shows.

The messages are the exact English texts on the scanner page; the page never builds ticket
messages itself, so a wording change is one edit here. Times are shown in the event's time zone.
"""

import datetime
from dataclasses import dataclass
from typing import Any

import config

CHECKED_IN = "{name} — printing"
ALREADY_CHECKED_IN = "Already checked in at {time}"
ALREADY_CHECKED_IN_NO_TIME = "Already checked in"
INVALID = "Not valid — please write your name on your badge"
SCAN_PRINT_FAILED = "Checked in, but the sticker wasn't sent — tap Reprint"
REPRINTING = "Reprinting {name}"
NOT_CHECKED_IN = "Not checked in yet — scan the ticket instead"
REPRINT_FAILED = "The sticker wasn't sent — tap Reprint again"
BAD_REQUEST = "Something was wrong with the request — try again"
UNAUTHORIZED = "Wrong PIN"
UNAVAILABLE = {
    "no_answer": "pretix did not answer — try again",
    "busy": "pretix is busy — try again in a few seconds",
    "access": "The system can't use pretix — call the organizer",
}
ERROR = "Something went wrong — try again"


@dataclass(frozen=True)
class Reading:
    """A pretix answer about a ticket, read.

    Attributes:
        kind: "valid", "already" (already checked in) or "refused".
        reason: For the log line: pretix's reason or status; empty for a valid ticket.
    """

    kind: str
    reason: str


def read_answer(body: dict[str, Any]) -> Reading:
    """Read a redeem answer.

    Args:
        body: pretix's JSON, which has "status".

    Returns:
        valid for status ok; already for the error already_redeemed; refused for every other
        error reason and for the statuses incomplete and exchange.
    """
    status = body.get("status")
    if status == "ok":
        return Reading("valid", "")
    if status == "error":
        reason = str(body.get("reason") or "error")
        return Reading("already" if reason == "already_redeemed" else "refused", reason)
    return Reading("refused", str(status))


def event_zone(name: str) -> tuple[datetime.tzinfo, str]:
    """Find the event's time zone.

    Args:
        name: The IANA name, for example "Europe/Bratislava".

    Returns:
        (zone, how): how is "zoneinfo", or "utc" when the runtime has no time zone data for that
        name, for the log line.
    """
    try:
        import zoneinfo

        return zoneinfo.ZoneInfo(name), "zoneinfo"
    except Exception:
        pass
    return datetime.timezone.utc, "utc"


def zone_from_env(fields: dict[str, Any]) -> datetime.tzinfo:
    """Find the event's time zone from the Lambda's environment.

    Args:
        fields: The log line's fields; gets time_zone when EVENT_TIMEZONE was not found.

    Returns:
        The zone of EVENT_TIMEZONE, else UTC.
    """
    zone, how = event_zone(config.env("EVENT_TIMEZONE", "Europe/Bratislava"))
    if how != "zoneinfo":
        fields["time_zone"] = how
    return zone


def latest_entry(position: dict[str, Any] | None, zone: datetime.tzinfo) -> datetime.datetime | None:
    """Find a ticket's latest entry check-in.

    Args:
        position: The position from a pretix answer; its "checkins" holds only successful
            check-ins on the requested list.
        zone: The event's time zone.

    Returns:
        The latest check-in's time with type "entry", in the event's time zone, or None when there
        is none or "checkins" is not a list.
    """
    checkins = (position or {}).get("checkins")
    if not isinstance(checkins, list):
        return None
    times = []
    for checkin in checkins:
        if not isinstance(checkin, dict) or checkin.get("type") != "entry":
            continue
        try:
            moment = datetime.datetime.fromisoformat(str(checkin.get("datetime")))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        times.append(moment.astimezone(zone))
    return max(times) if times else None
