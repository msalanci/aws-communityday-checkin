# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""What a pretix answer means for the phone, and every message text the phone shows.

The messages are the exact English texts on the scanner page; the page never builds ticket
messages itself, so a wording change is one edit here. Times are shown in the event's time zone.
"""

import datetime
import re
from dataclasses import dataclass
from typing import Any

from shared import config

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

OFFSET_PATTERN = re.compile(r"([+-])(\d{2}):(\d{2})")


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


def event_zone(name: str, utc_offset: str) -> tuple[datetime.tzinfo, str]:
    """Find the event's time zone.

    Args:
        name: The IANA name, for example "Europe/Bratislava".
        utc_offset: A fixed offset such as "+01:00", used only when the runtime has no time zone
            data; may be empty.

    Returns:
        (zone, how): how is "zoneinfo", "offset" or "utc", for the log line when it is not
        zoneinfo.
    """
    try:
        import zoneinfo

        return zoneinfo.ZoneInfo(name), "zoneinfo"
    except Exception:
        pass
    match = OFFSET_PATTERN.fullmatch(utc_offset or "")
    if match:
        sign = -1 if match.group(1) == "-" else 1
        delta = datetime.timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))
        return datetime.timezone(sign * delta), "offset"
    return datetime.timezone.utc, "utc"


def zone_from_env(fields: dict[str, Any]) -> datetime.tzinfo:
    """Find the event's time zone from the Lambda's environment.

    Args:
        fields: The log line's fields; gets time_zone when EVENT_TIMEZONE was not found.

    Returns:
        The zone of EVENT_TIMEZONE, else the fixed EVENT_UTC_OFFSET, else UTC.
    """
    zone, how = event_zone(config.env("EVENT_TIMEZONE", "Europe/Bratislava"), config.env("EVENT_UTC_OFFSET"))
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
        The latest entry check-in's time in the event's time zone, or None when there is none.
    """
    times = []
    for checkin in (position or {}).get("checkins") or []:
        if not isinstance(checkin, dict) or checkin.get("type", "entry") != "entry":
            continue
        try:
            moment = datetime.datetime.fromisoformat(str(checkin.get("datetime")))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        times.append(moment.astimezone(zone))
    return max(times) if times else None
