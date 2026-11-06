# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""Print laptop program: takes print requests from the print queue and prints name stickers.

Runs on the Windows print laptop, with the Brother QL-820NWB on USB. Its settings come from
the .env file next to this program (see .env.example): the sticker templates (one name line,
and optionally two name lines for long names) and printer,
the sticker's texts and fonts, and the AWS profile, region and queue. Without arguments it
runs the queue loop; --check describes the setup without printing; --test prints one
sticker without AWS. The launcher start-print-laptop.bat restarts it whenever it stops.
"""

import argparse
import datetime
import json
import os
import pathlib
import re
import signal
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from printed_ids import PrintedIds
from printer import ONE_LINE_PLACEHOLDERS, TWO_LINE_PLACEHOLDERS, LineFont, PrinterSetupError, StickerPrinter

PROGRAM_DIR = pathlib.Path(__file__).resolve().parent
ENV_FILE = PROGRAM_DIR / ".env"
PRINTED_IDS_FILE = PROGRAM_DIR / "printed_ids.txt"
LOCK_FILE = PROGRAM_DIR / "print_laptop.lock"
PRINT_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")
LINE_KEYS = {"Name": "NAME", "Attendee": "ATTENDEE", "Year": "YEAR"}
DEFAULT_TEST_NAME = "Ľubomír Šťastný"
MAX_RECEIVES = 5
WAIT_SECONDS = 5
RECHECK_SECONDS = 60
PRUNE_SECONDS = 3600
BACKOFF_FIRST_SECONDS = 15
BACKOFF_MAX_SECONDS = 120
MAX_PRINTER_ERRORS = 12


class ConfigError(Exception):
    """A setting in .env is missing or invalid; the message names the key."""


class RestartNeeded(Exception):
    """b-PAC keeps failing; only a fresh start of the program creates it again."""


@dataclass(frozen=True)
class Settings:
    """Everything the program reads from .env."""

    template_path: pathlib.Path
    template_2line_path: pathlib.Path | None
    printer_name: str
    roll: str
    attendee_text: str | None
    year_text: str | None
    fonts: dict[str, LineFont]
    name_fit_chars: int
    two_line_fit_chars: int
    name_min_size: int
    fill: float
    two_line_same_size: bool
    aws_profile: str
    aws_region: str
    queue_url: str


@dataclass(frozen=True)
class PrintRequest:
    """One print request: the ID that makes it unique, and the attendee's name."""

    print_id: str
    first_name: str
    last_name: str


@dataclass(frozen=True)
class Layout:
    """How one sticker is printed: which template, the text and size factor of each line."""

    template_path: pathlib.Path
    placeholders: dict[str, str]
    texts: dict[str, str | None]
    scales: dict[str, float]


@dataclass
class LoopState:
    """What the queue loop remembers from one round to the next."""

    printer_online: bool | None = None
    offline_said_at: float = float("-inf")
    roll_checked_at: float = float("-inf")
    roll_problem: str | None = None
    roll_blocks: bool = True
    pruned_at: float = float("-inf")
    failures: int = 0
    printer_errors: int = 0


class StopRequest:
    """Ctrl+C asks the loop to stop after the current step, so a sticker is never left half done."""

    def __init__(self) -> None:
        """Start with no stop asked for.

        Args:
            None.

        Returns:
            None.
        """
        self.requested = False

    def handle(self, _signum: int, _frame: Any) -> None:
        """React to Ctrl+C: the first one asks to stop between steps, a second one stops at once.

        Args:
            _signum: The signal number.
            _frame: The interrupted frame.

        Returns:
            None.

        Raises:
            KeyboardInterrupt: On the second Ctrl+C.
        """
        if self.requested:
            raise KeyboardInterrupt
        self.requested = True
        say("ℹ️", "Stopping after the current step (Ctrl+C again stops at once)")


def say(icon: str, text: str) -> None:
    """Show one console line with the local time and an icon.

    Args:
        icon: ✅ printed, ⏭ skipped, ❌ problem, ⚠️ warning, ℹ️ information.
        text: What happened.

    Returns:
        None. Prints to the console only; the program writes no log file.
    """
    print(f"{datetime.datetime.now():%H:%M:%S} {icon} {text}", flush=True)


def read_env(path: pathlib.Path) -> dict[str, str]:
    """Read KEY=VALUE lines from a .env file, taking values literally.

    Lines starting with # and blank lines are skipped; a value may be wrapped in single or
    double quotes, and backslashes stay as they are, so Windows paths work unquoted.

    Args:
        path: The .env file.

    Returns:
        The keys and their trimmed values; empty when the file does not exist.
    """
    if not path.is_file():
        return {}
    values = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _required(values: dict[str, str], key: str) -> str:
    """Read a setting that must be filled in.

    Args:
        values: The .env values.
        key: The setting's name.

    Returns:
        Its value.

    Raises:
        ConfigError: The setting is missing or empty.
    """
    value = values.get(key, "")
    if not value:
        raise ConfigError(f"{key} is missing in .env")
    return value


def _optional_number(values: dict[str, str], key: str, low: int, high: int) -> int | None:
    """Read an optional whole-number setting within limits.

    Args:
        values: The .env values.
        key: The setting's name.
        low: The smallest allowed value.
        high: The largest allowed value.

    Returns:
        The number, or None when the setting is empty.

    Raises:
        ConfigError: The value is not a whole number from low to high.
    """
    value = values.get(key, "")
    if not value:
        return None
    if not value.isdigit() or not low <= int(value) <= high:
        raise ConfigError(f"{key} must be a whole number from {low} to {high}, not {value!r}")
    return int(value)


def _whole_number(values: dict[str, str], key: str, default: int, low: int, high: int) -> int:
    """Read a whole-number setting within limits, with a default when it is empty.

    Args:
        values: The .env values.
        key: The setting's name.
        default: The value when the setting is empty.
        low: The smallest allowed value.
        high: The largest allowed value.

    Returns:
        The number.

    Raises:
        ConfigError: The value is not a whole number from low to high.
    """
    number = _optional_number(values, key, low, high)
    return default if number is None else number


def _yes_no(values: dict[str, str], key: str) -> bool | None:
    """Read an optional yes/no setting.

    Args:
        values: The .env values.
        key: The setting's name.

    Returns:
        True for yes, False for no, None when empty.

    Raises:
        ConfigError: The value is neither yes nor no.
    """
    value = values.get(key, "").lower()
    if not value:
        return None
    if value not in ("yes", "no"):
        raise ConfigError(f"{key} must be yes or no, not {value!r}")
    return value == "yes"


def load_settings(values: dict[str, str], needs_queue: bool) -> Settings:
    """Turn the .env values into settings, checking each one.

    Args:
        values: The .env values.
        needs_queue: True for the queue loop, which also needs the AWS settings.

    Returns:
        The settings.

    Raises:
        ConfigError: A required setting is missing, or a value is invalid.
    """
    fonts = {
        line: LineFont(
            name=values.get(f"STICKER_{key}_FONT") or None,
            size=_optional_number(values, f"STICKER_{key}_SIZE", 4, 72),
            bold=_yes_no(values, f"STICKER_{key}_BOLD"),
        )
        for line, key in LINE_KEYS.items()
    }
    two_line_name = LineFont(
        name=fonts["Name"].name,
        size=_optional_number(values, "STICKER_2LINE_NAME_SIZE", 4, 72),
        bold=fonts["Name"].bold,
    )
    fonts["FirstName"] = fonts["LastName"] = two_line_name
    template_2line = values.get("TEMPLATE_2LINE_PATH", "")
    aws = {key: _required(values, key) if needs_queue else values.get(key, "") for key in ("AWS_PROFILE", "AWS_REGION", "QUEUE_URL")}
    return Settings(
        template_path=_program_path(_required(values, "TEMPLATE_PATH")),
        template_2line_path=_program_path(template_2line) if template_2line else None,
        printer_name=_required(values, "PRINTER_NAME"),
        roll=values.get("ROLL", ""),
        attendee_text=values.get("STICKER_ATTENDEE_TEXT") or None,
        year_text=values.get("STICKER_YEAR_TEXT") or None,
        fonts=fonts,
        name_fit_chars=_whole_number(values, "STICKER_NAME_FIT_CHARS", 16, 1, 200),
        two_line_fit_chars=_whole_number(values, "STICKER_2LINE_FIT_CHARS", 20, 1, 200),
        name_min_size=_whole_number(values, "STICKER_NAME_MIN_SIZE", 8, 4, 72),
        fill=_whole_number(values, "STICKER_FILL_PERCENT", 90, 50, 100) / 100,
        two_line_same_size=bool(_yes_no(values, "STICKER_2LINE_SAME_SIZE")),
        aws_profile=aws["AWS_PROFILE"],
        aws_region=aws["AWS_REGION"],
        queue_url=aws["QUEUE_URL"],
    )


def _program_path(value: str) -> pathlib.Path:
    """Turn a path from .env into an absolute path, relative ones taken from the program's folder.

    Args:
        value: The path as written in .env.

    Returns:
        The absolute path.
    """
    path = pathlib.Path(value)
    return path if path.is_absolute() else PROGRAM_DIR / path


def full_name(first_name: str, last_name: str) -> str:
    """Join a first name and a last name with one space.

    Args:
        first_name: The attendee's first name; may be empty.
        last_name: The attendee's last name; may be empty.

    Returns:
        The name as printed, for example "Ján Novák", without stray spaces.
    """
    return " ".join(part for part in (first_name.strip(), last_name.strip()) if part)


def line_scale(text: str, fit_chars: int) -> float:
    """Give the factor for a line's font size, so a long line fits the sticker.

    Args:
        text: The line's text.
        fit_chars: The longest text that fits at the full size.

    Returns:
        1 up to fit_chars characters; fit_chars ÷ length beyond.
    """
    if len(text) <= fit_chars:
        return 1.0
    return fit_chars / len(text)


def split_name(first_name: str, last_name: str) -> tuple[str, str] | None:
    """Split a name into the two lines of the two-line sticker.

    Args:
        first_name: The attendee's first name (it may hold several given names).
        last_name: The attendee's last name.

    Returns:
        (first line, second line): the first and last name when both exist, otherwise the
        full name split at its last space; None when it cannot be split (one single word).
    """
    first, last = first_name.strip(), last_name.strip()
    if first and last:
        return first, last
    words = (first or last).rsplit(" ", 1)
    if len(words) == 2 and all(word.strip() for word in words):
        return words[0].strip(), words[1].strip()
    return None


def choose_layout(settings: Settings, first_name: str, last_name: str) -> Layout:
    """Pick the one-line or the two-line sticker for a name, with each line's text and size factor.

    A name up to STICKER_NAME_FIT_CHARS characters goes on one line. A longer one goes on two
    lines (first name, then last name) when a two-line template is set and the name can be
    split; each of those lines shrinks only if it is longer than STICKER_2LINE_FIT_CHARS.
    Otherwise the long name stays on one line and shrinks.

    Args:
        settings: The settings.
        first_name: The attendee's first name.
        last_name: The attendee's last name.

    Returns:
        The layout to print.
    """
    name = full_name(first_name, last_name)
    common = {"Attendee": settings.attendee_text, "Year": settings.year_text}
    parts = split_name(first_name, last_name)
    if len(name) > settings.name_fit_chars and settings.template_2line_path and parts:
        first, last = parts
        return Layout(
            template_path=settings.template_2line_path,
            placeholders=TWO_LINE_PLACEHOLDERS,
            texts={"FirstName": first, "LastName": last, **common},
            scales={
                "FirstName": line_scale(first, settings.two_line_fit_chars),
                "LastName": line_scale(last, settings.two_line_fit_chars),
            },
        )
    return Layout(
        template_path=settings.template_path,
        placeholders=ONE_LINE_PLACEHOLDERS,
        texts={"Name": name, **common},
        scales={"Name": line_scale(name, settings.name_fit_chars)},
    )


def parse_request(body: str) -> PrintRequest | None:
    """Read a print request from a queue message's body.

    Args:
        body: The message body, JSON with print_id, first_name and last_name.

    Returns:
        The print request, or None when the body is not a valid print request. A print ID
        must be 1-64 letters, digits or hyphens, so it fits one line of the printed-IDs file
        and the Windows print job's name.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    fields = [data.get(key) for key in ("print_id", "first_name", "last_name")]
    if not all(isinstance(value, str) for value in fields) or not PRINT_ID_PATTERN.fullmatch(fields[0]):
        return None
    return PrintRequest(*fields)


def roll_check(settings: Settings, printer: Any) -> tuple[str, bool]:
    """Compare the roll in the printer with the roll each template needs.

    Args:
        settings: The settings, for ROLL and both templates.
        printer: The StickerPrinter.

    Returns:
        (problem, blocks): an empty problem when the roll is right; blocks is True when
        nothing may be printed until it is fixed.
    """
    templates = [path for path in (settings.template_path, settings.template_2line_path) if path is not None]
    unchecked = False
    for template in templates:
        try:
            (loaded_name, loaded_id), (template_name, template_id) = printer.rolls(template)
        except Exception as error:
            return f"Cannot read the roll: {error}", True
        if not loaded_name and not loaded_id:
            return "No label roll loaded", True
        if settings.roll:
            if loaded_name != settings.roll:
                return f"Loaded roll {loaded_name!r} doesn't match ROLL {settings.roll!r}", True
            continue
        if not template_id:
            unchecked = True
        elif loaded_id != template_id:
            return f"Loaded roll {loaded_name!r} doesn't match {template.name}'s roll {template_name!r}", True
    return ("Roll not checked: set ROLL in .env", False) if unchecked else ("", False)


def printer_online(printer: Any) -> bool | None:
    """Ask whether the printer is online.

    Args:
        printer: The StickerPrinter.

    Returns:
        True or False as b-PAC answers; None when b-PAC raised an error instead.
    """
    try:
        return bool(printer.is_online())
    except Exception:
        return None


def one_round(
    settings: Settings,
    printer: Any,
    queue: Any,
    printed: PrintedIds,
    state: LoopState,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> None:
    """Do one round of the queue loop: check the printer and roll, then handle one print request.

    Args:
        settings: The settings.
        printer: The StickerPrinter.
        queue: The PrintQueue.
        printed: The record of printed print IDs.
        state: What the loop remembers between rounds.
        sleep: Waits the given seconds; replaceable in tests.
        clock: Returns a monotonic time in seconds; replaceable in tests.

    Returns:
        None. Prints at most one sticker, and deletes its print request only after the
        printer confirmed it. After a failed print it waits before the next one, longer each
        time, so a printer fault the online check misses does not run the queue into the DLQ.

    Raises:
        RestartNeeded: b-PAC raised errors in MAX_PRINTER_ERRORS rounds in a row.
    """
    now = clock()
    online = printer_online(printer)
    if online is None:
        state.printer_errors += 1
        if state.printer_errors >= MAX_PRINTER_ERRORS:
            raise RestartNeeded(f"b-PAC failed {state.printer_errors} times in a row")
    else:
        state.printer_errors = 0
    if not online:
        if state.printer_online is not False or now - state.offline_said_at >= RECHECK_SECONDS:
            say("❌", "Printer offline — check power and the USB cable")
            state.offline_said_at = now
        state.printer_online = False
        sleep(WAIT_SECONDS)
        return
    if state.printer_online is False:
        say("ℹ️", "Printer online again")
        state.roll_checked_at = float("-inf")
    state.printer_online = True

    if state.roll_blocks or now - state.roll_checked_at >= RECHECK_SECONDS:
        problem, blocks = roll_check(settings, printer)
        state.roll_checked_at = now
        if problem and problem != state.roll_problem:
            say("❌" if blocks else "⚠️", problem)
        elif not problem and state.roll_problem:
            say("ℹ️", "Label roll OK")
        state.roll_problem, state.roll_blocks = problem, blocks
        if blocks:
            sleep(WAIT_SECONDS)
            return

    if now - state.pruned_at >= PRUNE_SECONDS:
        state.pruned_at = now
        try:
            printed.prune()
        except OSError as error:
            say("⚠️", f"Could not tidy printed_ids.txt ({error}); trying again in an hour")

    try:
        message = queue.receive()
    except Exception as error:
        say("❌", f"No connection to AWS — retrying ({type(error).__name__})")
        sleep(WAIT_SECONDS)
        return
    if message is None:
        return
    request = parse_request(message.body)
    if request is None:
        say("❌", f"Unreadable print request — left in the queue; it moves to the DLQ after {MAX_RECEIVES} tries")
        return
    if printed.contains(request.print_id):
        delete_request(queue, message)
        say("⏭", "already printed")
        return
    name = full_name(request.first_name, request.last_name)
    layout = choose_layout(settings, request.first_name, request.last_name)
    try:
        result = printer.print_sticker(layout.template_path, layout.placeholders, layout.texts, request.print_id, layout.scales)
        detail = result.detail
    except Exception as error:
        result, detail = None, f"{type(error).__name__}: {error}"
    if result is None or not result.ok:
        say("❌", f"Print failed: {detail} (try {message.receive_count} of {MAX_RECEIVES})")
        state.failures += 1
        pause = min(BACKOFF_FIRST_SECONDS * 2 ** (state.failures - 1), BACKOFF_MAX_SECONDS)
        say("⚠️", f"Waiting {pause} s before the next sticker — check the labels and the cover")
        sleep(pause)
        return
    state.failures = 0
    try:
        printed.add(request.print_id)
    except OSError as error:
        say("⚠️", f"Could not record the sticker in printed_ids.txt ({error}); removing the request anyway")
    delete_request(queue, message)
    say("✅", name or "(no name)")


def delete_request(queue: Any, message: Any) -> None:
    """Delete a print request from the queue, reporting a failure instead of stopping.

    Args:
        queue: The PrintQueue.
        message: The message to delete.

    Returns:
        None. A failed delete is harmless: the request comes back, and the printed-IDs record
        skips it.
    """
    try:
        queue.delete(message)
    except Exception as error:
        say("⚠️", f"Could not remove the print request from the queue ({type(error).__name__}); it will be skipped")


def run_loop(
    settings: Settings,
    printer: Any,
    queue: Any,
    printed: PrintedIds,
    rounds: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    stop: StopRequest | None = None,
) -> None:
    """Run the queue loop until stopped.

    Args:
        settings: The settings.
        printer: The StickerPrinter.
        queue: The PrintQueue.
        printed: The record of printed print IDs.
        rounds: How many rounds to run; None runs until stopped (tests pass a number).
        sleep: Waits the given seconds; replaceable in tests.
        clock: Returns a monotonic time in seconds; replaceable in tests.
        stop: Set by Ctrl+C; the loop ends after the round in progress.

    Returns:
        None.

    Raises:
        RestartNeeded: b-PAC keeps failing.
    """
    state = LoopState()
    done = 0
    while (rounds is None or done < rounds) and not (stop and stop.requested):
        one_round(settings, printer, queue, printed, state, sleep, clock)
        done += 1


def hold_lock(path: pathlib.Path) -> Any | None:
    """Take the program's lock file, so a second copy cannot run the queue loop at the same time.

    The operating system releases the lock when the program ends, even after a crash.

    Args:
        path: The lock file.

    Returns:
        The open lock file, to keep open while the loop runs; None when another copy holds it.
    """
    handle = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def check(settings: Settings, printer: Any) -> int:
    """Describe the setup without printing: Python, b-PAC, printer, rolls, template lines, fonts.

    Args:
        settings: The settings.
        printer: The StickerPrinter.

    Returns:
        The exit code: 0.
    """
    say("ℹ️", f"Python {sys.version.split()[0]}, 64-bit: {sys.maxsize > 2**32}")
    say("ℹ️", f"One-line template: {settings.template_path}")
    say("ℹ️", f"Two-line template: {settings.template_2line_path or '(none: long names shrink on one line)'}")
    say("ℹ️", f"Printer: {settings.printer_name}; ROLL setting: {settings.roll or '(empty)'}")
    say(
        "ℹ️",
        f"Names over {settings.name_fit_chars} characters use two lines; each name line fits "
        f"{settings.fill:.0%} of the sticker's width, never below {settings.name_min_size} pt; "
        f"same size on two lines: {settings.two_line_same_size}",
    )
    templates = {settings.template_path: ONE_LINE_PLACEHOLDERS}
    if settings.template_2line_path:
        templates[settings.template_2line_path] = TWO_LINE_PLACEHOLDERS
    font_names = [font.name for font in settings.fonts.values() if font.name]
    for finding in printer.diagnose(templates, font_names):
        say("ℹ️", finding)
    return 0


def test_print(settings: Settings, printer: Any, name: str) -> int:
    """Print one sticker without AWS, as pretix would send the name: the last word is the last name.

    Args:
        settings: The settings.
        printer: The StickerPrinter.
        name: The full name to print.

    Returns:
        The exit code: 0 when the printer confirmed the print, 1 otherwise.
    """
    first, _, last = name.strip().rpartition(" ")
    if not first:
        first, last = last, ""
    layout = choose_layout(settings, first, last)
    result = printer.print_sticker(layout.template_path, layout.placeholders, layout.texts, f"test-{uuid.uuid4()}", layout.scales)
    lines = " / ".join(text for line, text in layout.texts.items() if line in ("Name", "FirstName", "LastName") and text)
    say("✅" if result.ok else "❌", f"{lines or '(no name)'} on {layout.template_path.name}: {result.detail}")
    return 0 if result.ok else 1


def run(settings: Settings, printer: Any) -> int:
    """Start the queue loop with the real print queue and the printed-IDs record.

    Args:
        settings: The settings.
        printer: The StickerPrinter.

    Returns:
        The exit code: 0 when stopped with Ctrl+C, 1 when b-PAC keeps failing (the launcher
        starts the program again), 2 for a setup problem: no Printed event, another copy
        running, or an AWS profile that cannot be used.
    """
    from queue_reader import PrintQueue

    if not printer.events_available():
        say("❌", "b-PAC's Printed event is not available, so no print could be confirmed; run --check")
        return 2
    lock = hold_lock(LOCK_FILE)
    if lock is None:
        say("❌", "Another copy of the print laptop program is already running; close the other window")
        return 2
    try:
        queue = PrintQueue(settings.aws_profile, settings.aws_region, settings.queue_url)
    except Exception as error:
        say("❌", f"Cannot use the AWS profile {settings.aws_profile!r}: {error}. Run: aws configure --profile {settings.aws_profile}")
        return 2
    printed = PrintedIds(PRINTED_IDS_FILE)
    printed.load()
    try:
        printed.prune()
    except OSError as error:
        say("⚠️", f"Could not tidy printed_ids.txt ({error}); trying again in an hour")
    say(
        "ℹ️",
        f"Print laptop ready: queue {queue.name()}, template {settings.template_path.name}, "
        f"printer {settings.printer_name}, confirmation by the Printed event",
    )
    stop = StopRequest()
    signal.signal(signal.SIGINT, stop.handle)
    try:
        run_loop(settings, printer, queue, printed, stop=stop)
    except KeyboardInterrupt:
        say("ℹ️", "Stopped")
    except RestartNeeded as error:
        say("❌", f"{error}; starting the program again")
        return 1
    else:
        say("ℹ️", "Stopped")
    finally:
        lock.close()
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Read the command line.

    Args:
        argv: The arguments after the program name; None reads sys.argv.

    Returns:
        The options: check, and test (None, or the name to print).
    """
    parser = argparse.ArgumentParser(description="Print name stickers from the print queue.")
    parser.add_argument("--check", action="store_true", help="describe the setup without printing; needs no AWS")
    parser.add_argument(
        "--test",
        nargs="?",
        const=DEFAULT_TEST_NAME,
        metavar="NAME",
        help=f"print one sticker without AWS (default name: {DEFAULT_TEST_NAME})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, env_path: pathlib.Path = ENV_FILE) -> int:
    """Run the program in the mode the command line asks for.

    Args:
        argv: The arguments after the program name; None reads sys.argv.
        env_path: The settings file.

    Returns:
        The exit code: 0 on success, 1 when a test print failed, 2 for a setup problem.
    """
    args = parse_args(argv)
    try:
        settings = load_settings(read_env(env_path), needs_queue=not args.check and args.test is None)
    except ConfigError as error:
        say("❌", str(error))
        return 2
    if sys.maxsize <= 2**32:
        say("❌", "This Python is 32-bit; install 64-bit Python 3.14")
        return 2
    if not args.check:
        for template in (settings.template_path, settings.template_2line_path):
            if template is not None and not template.is_file():
                say("❌", f"Template not found: {template}")
                return 2
    try:
        printer = StickerPrinter(
            settings.printer_name,
            settings.fonts,
            settings.name_min_size,
            fill=settings.fill,
            same_size=settings.two_line_same_size,
        )
    except PrinterSetupError as error:
        say("❌", str(error))
        return 2
    if args.check:
        return check(settings, printer)
    if args.test is not None:
        return test_print(settings, printer, args.test)
    return run(settings, printer)


if __name__ == "__main__":
    sys.exit(main())
