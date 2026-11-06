# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""Brother b-PAC adapter for the print laptop: fills the sticker template and prints it.

The only module of the print laptop's program that imports pywin32, and only when a
StickerPrinter is created, so the rest of the program imports and tests on any machine. It
opens a template made in P-touch Editor (the one-line or the two-line sticker), finds its lines
(b-PAC 3.4 reads no object names from a P-touch Editor 6 template, so by name, else placeholder
text, else order), sets their texts and fonts, prints through the Windows driver, and confirms
the print through b-PAC's Printed event, with the Windows print queue as the second witness
when the event is late.
"""

import math
import pathlib
import re
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

PROG_ID = "bpac.Document"
AUTO_CUT = 0x1
CONFIRM_SECONDS = 10
LONGEST_PRINT_SECONDS = 30
LATE_EVENT_SECONDS = 3
POLL_SECONDS = 0.2
ONE_LINE_PLACEHOLDERS = {"Name": "Name Surname", "Attendee": "Attendee", "Year": "2027"}
TWO_LINE_PLACEHOLDERS = {"FirstName": "Name", "LastName": "Surname", "Attendee": "Attendee", "Year": "2027"}
JOB_ERROR_FLAGS = 0x1 | 0x2 | 0x4 | 0x20 | 0x40 | 0x100 | 0x200 | 0x400
NAME_LINES = ("Name", "FirstName", "LastName")
MM_PER_POINT = 25.4 / 72
MEASURE_EM = 1000
KNOWN_COM_ERRORS = {
    -2147221164: "b-PAC is installed for the other bitness; install the 64-bit b-PAC",
    -2147221005: "b-PAC is not installed",
}


class PrinterSetupError(Exception):
    """b-PAC, the printer or the template cannot be used; the message says why."""


@dataclass(frozen=True)
class LineFont:
    """Font settings for one sticker line; None keeps what the template has."""

    name: str | None = None
    size: int | None = None
    bold: bool | None = None


@dataclass(frozen=True)
class PrintResult:
    """The outcome of one print: whether the printer confirmed it, and a short explanation."""

    ok: bool
    detail: str


def member(obj: Any, name: str) -> Any:
    """Read a b-PAC member that takes no arguments.

    pywin32 runs such b-PAC members on attribute access and returns their result; when it
    returns a callable instead, calling it gives the result. Calling a result again would
    fail or run the member twice.

    Args:
        obj: A b-PAC COM object.
        name: The member's name, for example "EndPrint" or "GetMediaId".

    Returns:
        The member's result.
    """
    value = getattr(obj, name)
    return value() if callable(value) else value


def safe_attribute(obj: Any, attribute: str) -> Any:
    """Read one attribute of a b-PAC object without failing.

    Args:
        obj: A b-PAC object.
        attribute: The attribute's name, for example "Text".

    Returns:
        The value, or None when it cannot be read.
    """
    try:
        return getattr(obj, attribute)
    except Exception:
        return None


def object_at(objects: Any, index: int) -> Any | None:
    """Fetch one object from b-PAC's object collection, whichever access style works.

    Args:
        objects: The document's Objects collection.
        index: The position to read.

    Returns:
        The object, or None when nothing can be read at that position.
    """
    for read in (lambda: objects.Item(index), lambda: objects[index]):
        try:
            found = read()
        except Exception:
            continue
        if found is not None:
            return found
    return None


def all_objects(document: Any) -> list[Any]:
    """Read every object of the open template, in the template's own order.

    Args:
        document: The b-PAC document with the template open.

    Returns:
        The objects; empty when the collection cannot be read.
    """
    try:
        objects = document.Objects
        count = int(member(objects, "Count") or 0)
    except Exception:
        return []
    start = 0 if object_at(objects, 0) is not None else 1
    found = []
    for index in range(start, start + count):
        obj = object_at(objects, index)
        if obj is not None:
            found.append(obj)
    return found


def find_lines(document: Any, placeholders: dict[str, str]) -> dict[str, tuple[Any | None, str]]:
    """Find the template's line objects: by object name, else by placeholder text, else by order.

    Args:
        document: The b-PAC document with the template open.
        placeholders: Each line's name and the placeholder text typed in the template, in
            line order, for example ONE_LINE_PLACEHOLDERS.

    Returns:
        For each line, the object (None when not found) and how it was found.
    """
    objects = all_objects(document)
    used: set[int] = set()
    lines: dict[str, tuple[Any | None, str]] = {}
    for line in placeholders:
        try:
            by_name = document.GetObject(line)
        except Exception:
            by_name = None
        if by_name is not None:
            lines[line] = (by_name, "object name")
            used.update(index for index, obj in enumerate(objects) if safe_attribute(obj, "Name") == line)
            continue
        lines[line] = (None, "")
        for index, obj in enumerate(objects):
            text = str(safe_attribute(obj, "Text") or "").strip().casefold()
            if index not in used and text == placeholders[line].casefold():
                used.add(index)
                lines[line] = (obj, "placeholder text")
                break
    for line in placeholders:
        if lines[line][0] is not None:
            continue
        for index, obj in enumerate(objects):
            if index not in used:
                used.add(index)
                lines[line] = (obj, f"order (object #{index})")
                break
    return lines


def scaled_tenths(base_tenths: int, scale: float, min_size: int) -> int:
    """Shrink a font size for a long name, in b-PAC's tenths of a point.

    Args:
        base_tenths: The full size in tenths of a point, for example 200 for 20 pt.
        scale: The factor for the name's length; 1 or more keeps the full size.
        min_size: The smallest size in points a long name may shrink to.

    Returns:
        The size to set, in tenths of a point; never larger than the full size.
    """
    if scale >= 1:
        return base_tenths
    return min(base_tenths, max(min_size * 10, int(base_tenths * scale)))


def tape_width_mm(media_name: str) -> float | None:
    """Read the tape width from b-PAC's media name.

    Args:
        media_name: The media name, for example "62mm" or "29mm x 90mm".

    Returns:
        The first width in millimetres, for example 62.0; None when the name has none.
    """
    match = re.search(r"(\d+(?:\.\d+)?)\s*mm", media_name)
    return float(match.group(1)) if match else None


def fitted_tenths(width_em: float, base_tenths: int, available_mm: float, min_size: int) -> int:
    """Give the largest font size at which a line fits the available width, in tenths of a point.

    Args:
        width_em: The line's width at a font size of 1 em, measured in its own font.
        base_tenths: The full size, which the line never exceeds.
        available_mm: The width the line may use, in millimetres.
        min_size: The smallest size in points a line may shrink to.

    Returns:
        The size in tenths of a point, from min_size × 10 up to base_tenths.
    """
    if width_em <= 0:
        return base_tenths
    fit_tenths = math.floor(available_mm / (width_em * MM_PER_POINT) * 10)
    return min(base_tenths, max(min_size * 10, fit_tenths))


def equalize_name_lines(sizes: dict[str, int | None]) -> dict[str, int | None]:
    """Give the first-name and last-name lines the same size: the smaller of the two.

    Args:
        sizes: The size per line in tenths of a point.

    Returns:
        The sizes, with FirstName and LastName equal when both are set.
    """
    pair = [sizes.get("FirstName"), sizes.get("LastName")]
    if None in pair:
        return sizes
    smallest = min(pair)
    return {**sizes, "FirstName": smallest, "LastName": smallest}


def apply_font(obj: Any, font: LineFont, size_tenths: int | None) -> None:
    """Set a template object's font name, size and boldness where a value is given.

    Args:
        obj: A b-PAC text object.
        font: The font settings; None values keep the template's.
        size_tenths: The size in tenths of a point, or None to keep the template's.

    Returns:
        None. Changes the object in the open template only.

    Raises:
        PrinterSetupError: b-PAC answered False to one of the settings.
    """
    settings = []
    if font.name:
        settings.append(("SetFontName", font.name))
    if size_tenths is not None:
        settings.append(("SetFontMaxPoint", size_tenths))
    if font.bold is not None:
        settings.append(("SetFontBold", font.bold))
    for method, value in settings:
        if getattr(obj, method)(value) is False:
            raise PrinterSetupError(f"b-PAC refused {method}({value!r})")


def load_windows_modules() -> SimpleNamespace:
    """Import the pywin32 modules the printer needs.

    Args:
        None.

    Returns:
        A namespace with pythoncom, pywintypes, win32gui, win32print, win32com.client as
        client, and win32com.client's gencache and selecttlb.

    Raises:
        PrinterSetupError: pywin32 is not installed in this Python.
    """
    try:
        import pythoncom
        import pywintypes
        import win32com.client
        import win32gui
        import win32print
        from win32com.client import gencache, selecttlb
    except ImportError as error:
        raise PrinterSetupError(
            f"pywin32 is missing ({error}); run: py -3.14 -m pip install -r requirements.txt"
        ) from error
    return SimpleNamespace(
        pythoncom=pythoncom,
        pywintypes=pywintypes,
        client=win32com.client,
        gencache=gencache,
        selecttlb=selecttlb,
        win32gui=win32gui,
        win32print=win32print,
    )


def version_number(text: str) -> int:
    """Read a type library version part, which the registry may store as hex or decimal.

    Args:
        text: The version part, for example "3" or "a".

    Returns:
        The number.
    """
    try:
        return int(text, 16)
    except ValueError:
        return int(text)


def ensure_type_library(windows: SimpleNamespace) -> bool:
    """Generate pywin32's support module for b-PAC's type library, which b-PAC's events need.

    pywin32 cannot generate it from the b-PAC object itself, so the library is looked up
    among the registered type libraries by its name.

    Args:
        windows: The pywin32 modules.

    Returns:
        True when the module was generated or already existed; False otherwise.
    """
    for spec in windows.selecttlb.EnumTlbs():
        if not any(word in (spec.desc or "").lower() for word in ("b-pac", "bpac")):
            continue
        try:
            windows.gencache.EnsureModule(
                spec.clsid, spec.lcid, version_number(spec.major), version_number(spec.minor)
            )
        except Exception:
            continue
        return True
    return False


class StickerPrinter:
    """The QL-820NWB as b-PAC drives it: one b-PAC document, reused for every print."""

    def __init__(
        self,
        printer_name: str,
        fonts: dict[str, LineFont],
        name_min_size: int,
        fill: float = 0.9,
        same_size: bool = False,
    ) -> None:
        """Start b-PAC, check the printer is installed, and subscribe to print confirmations.

        Args:
            printer_name: The Windows printer name, for example "Brother QL-820NWB".
            fonts: Font settings per line ("Name", "FirstName", "LastName", "Attendee", "Year").
            name_min_size: The smallest size in points a name line may shrink to.
            fill: The share of the sticker's width a name line may use, for example 0.9.
            same_size: Whether the two-line sticker's first and last name share one size.

        Returns:
            None.

        Raises:
            PrinterSetupError: pywin32 or b-PAC is missing, or the printer is not installed.
        """
        self._windows = load_windows_modules()
        self._printer_name = printer_name
        self._fonts = fonts
        self._name_min_size = name_min_size
        self._fill = fill
        self._same_size = same_size
        try:
            self._document = self._windows.client.DispatchEx(PROG_ID)
        except self._windows.pywintypes.com_error as error:
            hresult = error.args[0] if error.args else None
            raise PrinterSetupError(KNOWN_COM_ERRORS.get(hresult, f"b-PAC cannot start: {error}")) from error
        installed = self.installed_printers()
        if printer_name not in installed:
            raise PrinterSetupError(f"Printer {printer_name!r} is not installed; installed printers: {installed}")
        self._events: list[tuple[Any, Any]] = []
        self._sink = self._bind_printed_event()

    def events_available(self) -> bool:
        """Tell whether prints are confirmed by b-PAC's Printed event.

        Args:
            None.

        Returns:
            True when b-PAC's Printed event is bound; without it the queue loop refuses to start.
        """
        return self._sink is not None

    def installed_printers(self) -> list[str]:
        """List the printers Windows has installed.

        Args:
            None.

        Returns:
            The printer names.
        """
        return list(member(self._document.Printer, "GetInstalledPrinters") or [])

    def is_online(self) -> bool:
        """Tell whether the printer is switched on and connected.

        Args:
            None.

        Returns:
            True when b-PAC reports the printer online.
        """
        return bool(self._document.Printer.IsPrinterOnline(self._printer_name))

    def rolls(self, template_path: pathlib.Path) -> tuple[tuple[str, int], tuple[str, int]]:
        """Read the roll loaded in the printer and the roll a template is made for.

        Args:
            template_path: The template whose roll to read.

        Returns:
            (loaded, template), each as (media name, media ID); an empty name and ID 0 mean
            no roll.

        Raises:
            PrinterSetupError: The template cannot be opened.
        """
        self._open(template_path)
        try:
            printer = self._document.Printer
            loaded = (str(member(printer, "GetMediaName") or ""), int(member(printer, "GetMediaId") or 0))
            template = (
                str(member(self._document, "GetMediaName") or ""),
                int(member(self._document, "GetMediaId") or 0),
            )
        finally:
            member(self._document, "Close")
        return loaded, template

    def installed_fonts(self) -> set[str]:
        """List the font families installed on this Windows machine.

        Args:
            None.

        Returns:
            The installed font family names.
        """
        names: set[str] = set()

        def collect(font: Any, _metric: Any, _font_type: Any, found: set[str]) -> bool:
            """Store one font family name.

            Args:
                font: The font's LOGFONT.
                _metric: Its text metrics.
                _font_type: Its font type.
                found: The set the names are collected in.

            Returns:
                True, so Windows keeps listing.
            """
            found.add(font.lfFaceName)
            return True

        handle = self._windows.win32gui.GetDC(0)
        try:
            self._windows.win32gui.EnumFontFamilies(handle, None, collect, names)
        finally:
            self._windows.win32gui.ReleaseDC(0, handle)
        return names

    def diagnose(self, templates: dict[pathlib.Path, dict[str, str]], font_names: list[str]) -> list[str]:
        """Describe everything the program depends on, without printing.

        Args:
            templates: Each template to check, with its line placeholders.
            font_names: The fonts the settings name, to check they are installed.

        Returns:
            One line of text per finding; a template that cannot be opened is reported, not raised.
        """
        confirmation = "b-PAC's Printed event" if self.events_available() else "NOT AVAILABLE (the queue loop will not start)"
        findings = [
            f"Print confirmation: {confirmation}",
            f"Installed printers: {self.installed_printers()}",
            f"Printer online: {self.is_online()}",
        ]
        for template_path, placeholders in templates.items():
            try:
                loaded, template = self.rolls(template_path)
                self._open(template_path)
            except PrinterSetupError as error:
                findings.append(f"{template_path.name}: {error}")
                continue
            findings.append(f"{template_path.name}: loaded roll {loaded[0]!r} (ID {loaded[1]}), template's roll {template[0]!r} (ID {template[1]})")
            available = self._available_mm()
            findings.append(
                f"{template_path.name}: name lines may use {available:.1f} mm" if available
                else f"{template_path.name}: sticker width unknown; long names shrink by length instead"
            )
            try:
                for line, (obj, how) in find_lines(self._document, placeholders).items():
                    if obj is None:
                        findings.append(f"{template_path.name} line {line}: NOT FOUND (placeholder {placeholders[line]!r})")
                        continue
                    size = member(obj, "GetFontMaxPoint") or 0
                    findings.append(
                        f"{template_path.name} line {line}: found by {how}; text {safe_attribute(obj, 'Text')!r}; "
                        f"font {member(obj, 'GetFontName')!r} {size / 10:g} pt, bold {member(obj, 'GetFontBold')}"
                    )
            finally:
                member(self._document, "Close")
        installed = self.installed_fonts()
        for name in sorted(set(font_names)):
            findings.append(f"Font {name!r} installed: {name in installed}")
        return findings

    def print_sticker(
        self,
        template_path: pathlib.Path,
        placeholders: dict[str, str],
        texts: dict[str, str | None],
        print_id: str,
        scales: dict[str, float],
    ) -> PrintResult:
        """Fill a template, print one sticker, and wait for the printer's confirmation.

        Args:
            template_path: The template to print.
            placeholders: Its lines and their placeholder texts.
            texts: The text per line; None keeps the template's.
            print_id: The print request's ID; it names the Windows print job.
            scales: The factor per line for its font size; below 1 shrinks a long line.

        Returns:
            Whether the print was confirmed, with a short explanation. A failed print's job is
            removed from the Windows print queue, so a retry is the only copy.
        """
        document_name = f"sticker {print_id}"
        self._windows.pythoncom.PumpWaitingMessages()
        self._events.clear()
        try:
            self._open(template_path)
        except PrinterSetupError as error:
            return PrintResult(False, str(error))
        try:
            found = find_lines(self._document, placeholders)
            missing = [line for line, (obj, _how) in found.items() if obj is None]
            if missing:
                return PrintResult(False, f"{template_path.name} has no text box for line {missing[0]}")
            sizes = self._sizes(found, texts, scales)
            for line, (obj, _how) in found.items():
                text = texts.get(line)
                if text is not None:
                    obj.Text = text
                apply_font(obj, self._fonts.get(line, LineFont()), sizes.get(line))
            if not self._document.StartPrint(document_name, AUTO_CUT):
                return self._fail(document_name, f"StartPrint failed: {self._printer_error()}")
            if not self._document.PrintOut(1, 0):
                return self._fail(document_name, f"PrintOut failed: {self._printer_error()}")
            if not member(self._document, "EndPrint"):
                return self._fail(document_name, f"EndPrint failed: {self._printer_error()}")
            return self._confirm(document_name)
        except Exception as error:
            return self._fail(document_name, f"b-PAC error: {error}")
        finally:
            try:
                member(self._document, "Close")
            except Exception:
                pass

    def _open(self, template_path: pathlib.Path) -> None:
        """Open a template and point it at the printer.

        Args:
            template_path: The template to open.

        Returns:
            None.

        Raises:
            PrinterSetupError: The template file is missing or b-PAC cannot open it.
        """
        if not template_path.is_file():
            raise PrinterSetupError(f"Template not found: {template_path}")
        if not self._document.Open(str(template_path)):
            raise PrinterSetupError(f"b-PAC cannot open the template: {template_path}")
        if self._document.SetPrinter(self._printer_name, False) is False:
            raise PrinterSetupError(f"b-PAC cannot select the printer {self._printer_name!r}")

    def _sizes(
        self,
        found: dict[str, tuple[Any, str]],
        texts: dict[str, str | None],
        scales: dict[str, float],
    ) -> dict[str, int | None]:
        """Work out each line's font size in tenths of a point.

        A name line is as large as fits the sticker's width, measured in its own font, up to
        its full size; when the width cannot be measured it shrinks by its length instead.
        Other lines keep their configured or template size.

        Args:
            found: Each line's object in the open template.
            texts: The text per line; None keeps the template's.
            scales: The length-based factor per line, the fallback.

        Returns:
            The size per line, or None to keep the template's.
        """
        available = self._available_mm()
        sizes: dict[str, int | None] = {}
        for line, (obj, _how) in found.items():
            font = self._fonts.get(line, LineFont())
            if line not in NAME_LINES:
                sizes[line] = font.size * 10 if font.size is not None else None
                continue
            base = font.size * 10 if font.size is not None else int(member(obj, "GetFontMaxPoint") or 0)
            if base <= 0:
                sizes[line] = None
                continue
            text = texts.get(line)
            if text is None:
                text = str(safe_attribute(obj, "Text") or "")
            font_name = font.name or str(member(obj, "GetFontName") or "Arial")
            bold = font.bold if font.bold is not None else bool(member(obj, "GetFontBold"))
            width_em = self._text_width_em(text, font_name, bold) if available else 0.0
            if width_em > 0:
                sizes[line] = fitted_tenths(width_em, base, available, self._name_min_size)
            else:
                sizes[line] = scaled_tenths(base, scales.get(line, 1.0), self._name_min_size)
        return equalize_name_lines(sizes) if self._same_size else sizes

    def _available_mm(self) -> float | None:
        """Give the width a name line may use on the open template's sticker.

        b-PAC reports the sticker's length and the tape's width in one unit; the tape's width
        in millimetres, read from the media name, converts the length to millimetres.

        Args:
            None.

        Returns:
            The sticker's length in millimetres times the fill share; None when unknown.
        """
        try:
            length = float(member(self._document, "Length") or 0)
            width = float(member(self._document, "Width") or 0)
            tape_mm = tape_width_mm(str(member(self._document, "GetMediaName") or ""))
        except Exception:
            return None
        if length <= 0 or width <= 0 or not tape_mm:
            return None
        return length / (width / tape_mm) * self._fill

    def _text_width_em(self, text: str, font_name: str, bold: bool) -> float:
        """Measure a text's width in a font, as a multiple of the font size.

        Args:
            text: The text.
            font_name: The font, for example "Arial".
            bold: Whether the font is bold.

        Returns:
            The width in em; 0 when the text is empty or Windows cannot measure it.
        """
        if not text:
            return 0.0
        gui = self._windows.win32gui
        try:
            context = gui.CreateCompatibleDC(0)
            try:
                logfont = gui.LOGFONT()
                logfont.lfFaceName = font_name
                logfont.lfHeight = -MEASURE_EM
                logfont.lfWeight = 700 if bold else 400
                handle = gui.CreateFontIndirect(logfont)
                previous = gui.SelectObject(context, handle)
                try:
                    width, _height = gui.GetTextExtentPoint32(context, text)
                finally:
                    gui.SelectObject(context, previous)
                    gui.DeleteObject(handle)
            finally:
                gui.DeleteDC(context)
        except Exception:
            return 0.0
        return width / MEASURE_EM

    def _bind_printed_event(self) -> Any | None:
        """Subscribe to b-PAC's Printed event, which confirms each print.

        Args:
            None.

        Returns:
            The event sink, kept alive by the caller; None when the event cannot be bound.
        """
        events = self._events

        def on_printed(_sink: Any, status: Any, value: Any) -> None:
            """Store one print-completion event.

            Args:
                _sink: The event sink object pywin32 created.
                status: b-PAC's completion status; 0 for a good print.
                value: b-PAC's completion value.

            Returns:
                None.
            """
            events.append((status, value))

        ensure_type_library(self._windows)
        try:
            base = self._windows.client.getevents(PROG_ID)
            if base is None:
                return None
            sink_class = type(base)("PrintedSink", (base,), {"OnPrinted": on_printed})
            return sink_class(self._document)
        except Exception:
            return None

    def _confirm(self, document_name: str) -> PrintResult:
        """Wait for the print's confirmation.

        b-PAC's Printed event decides as soon as it arrives. Until then the Windows print queue
        is watched: a job seen there and gone again without an error flag counts as printed
        once 10 s have passed, and a job still printing without an error is waited for up to
        30 s, because deleting a slow job that the printer already received would make the
        retry a second sticker. A decision taken without the event waits a few seconds more
        for a late one, so that event can neither be missed nor taken for the next sticker's.
        A queue that cannot be read tells nothing and confirms nothing.

        Args:
            document_name: The print job's document name.

        Returns:
            Confirmed or failed, with how it was decided. A failed print's job is removed from
            the Windows print queue.
        """
        started = time.monotonic()
        seen = left = False
        error_flags = 0
        while True:
            elapsed = time.monotonic() - started
            event = self._next_event()
            if event is not None:
                return self._event_result(document_name, event)
            try:
                job = self._job(document_name)
            except Exception:
                job, readable = None, False
            else:
                readable = True
            if job is not None:
                seen = True
                error_flags |= int(job.get("Status") or 0) & JOB_ERROR_FLAGS
            elif readable and seen:
                left = True
            if elapsed >= CONFIRM_SECONDS and (left or not seen or error_flags or elapsed >= LONGEST_PRINT_SECONDS):
                break
            time.sleep(POLL_SECONDS)
        late = self._wait_for_event(LATE_EVENT_SECONDS)
        if late is not None:
            return self._event_result(document_name, late)
        if left and not error_flags:
            return PrintResult(True, "the job left the Windows print queue without an error")
        if error_flags:
            return self._fail(document_name, f"the Windows print job reported status {error_flags:#x}; {self._printer_error()}")
        return self._fail(document_name, f"no confirmation within {CONFIRM_SECONDS} s; {self._printer_error()}")

    def _next_event(self) -> tuple[Any, Any] | None:
        """Deliver waiting COM messages and take the oldest Printed event, if any.

        Args:
            None.

        Returns:
            (status, value) of the event, or None when none has arrived.
        """
        self._windows.pythoncom.PumpWaitingMessages()
        return self._events.pop(0) if self._events else None

    def _wait_for_event(self, seconds: float) -> tuple[Any, Any] | None:
        """Wait a while for a Printed event.

        Args:
            seconds: How long to wait.

        Returns:
            (status, value) of the first event, or None when none arrived in time.
        """
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            event = self._next_event()
            if event is not None:
                return event
            time.sleep(POLL_SECONDS)
        return self._next_event()

    def _event_result(self, document_name: str, event: tuple[Any, Any]) -> PrintResult:
        """Turn a Printed event into the print's result.

        Args:
            document_name: The print job's document name, to remove it on failure.
            event: (status, value) from b-PAC; status 0 is a good print.

        Returns:
            Confirmed for status 0, a failure otherwise.
        """
        status, value = event
        if status == 0:
            return PrintResult(True, "confirmed by the printer")
        return self._fail(document_name, f"printer reported {status}/{value}; {self._printer_error()}")

    def _fail(self, document_name: str, detail: str) -> PrintResult:
        """Remove a failed print's job from the Windows print queue and report the failure.

        Args:
            document_name: The print job's document name.
            detail: What went wrong.

        Returns:
            A failed PrintResult with the detail.
        """
        try:
            job = self._job(document_name)
            if job is not None:
                handle = self._windows.win32print.OpenPrinter(self._printer_name)
                try:
                    self._windows.win32print.SetJob(
                        handle, job["JobId"], 0, None, self._windows.win32print.JOB_CONTROL_DELETE
                    )
                finally:
                    self._windows.win32print.ClosePrinter(handle)
        except Exception as error:
            detail = f"{detail}; the stuck job could not be removed: {error}"
        return PrintResult(False, detail)

    def _job(self, document_name: str) -> dict[str, Any] | None:
        """Find a print job in the printer's Windows print queue.

        Args:
            document_name: The print job's document name.

        Returns:
            The job as win32print reports it, or None when it is not in the queue.

        Raises:
            Exception: win32print cannot open the printer or read its queue.
        """
        handle = self._windows.win32print.OpenPrinter(self._printer_name)
        try:
            for job in self._windows.win32print.EnumJobs(handle, 0, 999, 1):
                if job.get("pDocument") == document_name:
                    return job
            return None
        finally:
            self._windows.win32print.ClosePrinter(handle)

    def _printer_error(self) -> str:
        """Read the printer's last error from b-PAC.

        Args:
            None.

        Returns:
            The error code and text, for example "error 0".
        """
        printer = self._document.Printer
        code = safe_attribute(printer, "ErrorCode")
        text = safe_attribute(printer, "ErrorString") or ""
        return f"error {code} {text}".strip()
