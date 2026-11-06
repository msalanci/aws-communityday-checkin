# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""The print laptop's record of printed print IDs, kept on disk so a crash cannot print a sticker twice.

If the program prints and then stops before deleting the print request, SQS delivers it
again; this record lets the program skip it. One line per printed sticker,
"<print_id><TAB><unix time>", in printed_ids.txt next to the program: IDs only, no names.
Entries older than 48 hours are dropped.
"""

import os
import pathlib
import time
from typing import Callable

MAX_AGE_SECONDS = 48 * 3600


class PrintedIds:
    """The set of print IDs printed in the last 48 hours, mirrored in a file."""

    def __init__(self, path: pathlib.Path, max_age_seconds: int = MAX_AGE_SECONDS, clock: Callable[[], float] = time.time) -> None:
        """Prepare an empty record that lives in the given file.

        Args:
            path: The record's file.
            max_age_seconds: How long an ID is remembered.
            clock: Returns the current Unix time; replaceable in tests.

        Returns:
            None.
        """
        self._path = path
        self._max_age = max_age_seconds
        self._clock = clock
        self._printed: dict[str, float] = {}

    def load(self) -> None:
        """Read the file, ignoring unreadable lines and entries that are too old.

        Args:
            None.

        Returns:
            None. A missing file means nothing has been printed yet; unreadable lines are
            skipped, so a damaged file never stops the program.
        """
        self._printed = {}
        if not self._path.is_file():
            return
        oldest = self._clock() - self._max_age
        for line in self._path.read_text(encoding="utf-8", errors="replace").splitlines():
            print_id, _, stamp = line.partition("\t")
            try:
                printed_at = float(stamp)
            except ValueError:
                continue
            if print_id and "\ufffd" not in print_id and printed_at >= oldest:
                self._printed[print_id] = printed_at

    def contains(self, print_id: str) -> bool:
        """Tell whether a print ID has already been printed.

        Args:
            print_id: The print request's ID.

        Returns:
            True when it is in the record.
        """
        return print_id in self._printed

    def add(self, print_id: str) -> None:
        """Record a printed print ID, flushed to disk before returning.

        Args:
            print_id: The print request's ID.

        Returns:
            None. Appends one line to the file.
        """
        now = self._clock()
        self._printed[print_id] = now
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(f"{print_id}\t{now:.0f}\n")
            handle.flush()
            os.fsync(handle.fileno())

    def prune(self) -> None:
        """Drop entries older than the maximum age, in memory and in the file.

        Args:
            None.

        Returns:
            None. Rewrites the file with the remaining entries, through a temporary file that
            replaces it in one step, so a crash mid-write cannot leave it empty.

        Raises:
            OSError: The file cannot be written or replaced, for example while a virus scanner
                holds it; the record in memory is already pruned.
        """
        oldest = self._clock() - self._max_age
        self._printed = {key: value for key, value in self._printed.items() if value >= oldest}
        lines = "".join(f"{key}\t{value:.0f}\n" for key, value in self._printed.items())
        temporary = self._path.with_name(self._path.name + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(lines)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)
