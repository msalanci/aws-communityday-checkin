@REM Copyright (c) 2026-2027 Michal Salanci
@REM SPDX-License-Identifier: MIT
@echo off
REM Runs the print laptop's program and restarts it 5 seconds after it stops, for any reason.
REM Start it by double-click on the event morning; close this window to stop it.
REM Uses .venv\Scripts\python.exe when a virtual environment exists next to this file, py -3.14 otherwise.
cd /d "%~dp0"
:loop
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" print_laptop.py
) else (
    py -3.14 print_laptop.py
)
echo Restarting in 5 s
timeout /t 5 /nobreak >nul
goto loop
