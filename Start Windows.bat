@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 -I -X utf8 gui.py
) else (
  python -I -X utf8 gui.py
)
if errorlevel 1 (
  echo Install Python 3.10 or newer from python.org, or use the portable Windows executable.
  pause
)
