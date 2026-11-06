# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""Attendee names from pretix, cleaned, because walk-ins type their names seconds before the scan.

Cleaning removes control and format characters (such as text-direction marks), collapses
whitespace and cuts each part to 64 characters.
"""

import re
import unicodedata
from typing import Any

MAX_PART = 64
REMOVED_CATEGORIES = {"Cc", "Cf"}


def clean(value: Any) -> str:
    """Clean one name part.

    Args:
        value: The text from pretix; anything that is not a string counts as empty.

    Returns:
        The cleaned text, at most 64 characters; empty when nothing is left.
    """
    if not isinstance(value, str):
        return ""
    kept = "".join(
        character
        for character in value
        if character.isspace() or unicodedata.category(character) not in REMOVED_CATEGORIES
    )
    return re.sub(r"\s+", " ", kept).strip()[:MAX_PART].strip()


def name_from(position: dict[str, Any] | None) -> tuple[str, str]:
    """Take the attendee's first and last name from a pretix position.

    Args:
        position: The position from a pretix answer; None when the answer has none.

    Returns:
        (first_name, last_name), cleaned. The given and family name when pretix has them,
        otherwise attendee_name as the first name; both empty means the ticket has no name.
    """
    position = position or {}
    parts = position.get("attendee_name_parts")
    parts = parts if isinstance(parts, dict) else {}
    first, last = clean(parts.get("given_name")), clean(parts.get("family_name"))
    if not first and not last:
        first = clean(position.get("attendee_name"))
    return first, last


def full_name(first_name: str, last_name: str) -> str:
    """Join a first and a last name with one space.

    Args:
        first_name: The first name; may be empty.
        last_name: The last name; may be empty.

    Returns:
        The full name, without stray spaces.
    """
    return " ".join(part for part in (first_name.strip(), last_name.strip()) if part)
