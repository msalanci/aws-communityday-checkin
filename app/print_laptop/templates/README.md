<!-- Copyright (c) 2026-2027 Michal Salanci. SPDX-License-Identifier: MIT -->

# Sticker templates

The two P-touch Editor templates the print program fills. Copy both to the **Desktop of the print computer**; the `.env` points there (`TEMPLATE_PATH=C:\Users\<windows-user>\Desktop\attendee.lbx`, `TEMPLATE_2LINE_PATH=C:\Users\<windows-user>\Desktop\attendee-2line.lbx`). They are not in `print-laptop.zip`, so a new zip never overwrites a template you changed on the print computer.

| File | Used for | Its text boxes (their placeholder texts) |
|---|---|---|
| `attendee.lbx` | Names up to 16 characters (`STICKER_NAME_FIT_CHARS`) | `Name Surname`, `attendee`, `2027` |
| `attendee-2line.lbx` | Longer names: first name and last name on two lines | `Name`, `Surname`, `attendee`, `2027` |

**Made for:** the Brother QL-820NWB with the **DK-22205** roll (62 mm continuous paper), a label **62 × 40 mm**, Arial: the name lines bold 20 pt, "attendee" regular 10 pt, the year bold 10 pt. They started from Brother's own 62 mm name-badge sample.

The program finds each line by its placeholder text (capitals do not matter), so keep the placeholders as they are; the `.env` puts the real texts in (`STICKER_ATTENDEE_TEXT`, `STICKER_YEAR_TEXT`), and its font settings win over the template's.

**Another roll or another length:** open the template from the print computer's Desktop in P-touch Editor, choose your roll (File → Printer/Page Setup → Check Media) and length, keep the boxes and their placeholders, and save it: under the same name, or under a new name and then point `TEMPLATE_PATH` (or `TEMPLATE_2LINE_PATH`) in the `.env` at it. Do the same with the other template. Then set `ROLL` in the `.env` to the loaded roll's name as `print_laptop.py --check` shows it.
