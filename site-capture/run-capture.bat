@echo off
setlocal
REM ------------------------------------------------------------------
REM  Site capture — double-click to run.
REM  Output goes to the "capture" folder next to this site-capture folder.
REM  Optional: drag a different URL onto this file, or run:
REM     run-capture.bat https://example.ca
REM ------------------------------------------------------------------
set "HERE=%~dp0"
set "OUT=%HERE%..\capture"
set "URL=%~1"
if "%URL%"=="" set "URL=https://peacecountryinstallations.ca"
set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Get it from https://www.python.org/downloads/
  echo  ^(tick "Add python.exe to PATH" during install^), then run this again.
  pause & exit /b 1
)

if not exist "%HERE%.venv\Scripts\python.exe" (
  echo First run: setting up Playwright + Chromium ^(one-time, ~2 minutes^)...
  python -m venv "%HERE%.venv" || (pause & exit /b 1)
  "%HERE%.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  "%HERE%.venv\Scripts\python.exe" -m pip install --quiet playwright || (pause & exit /b 1)
  "%HERE%.venv\Scripts\python.exe" -m playwright install chromium || (pause & exit /b 1)
)

"%HERE%.venv\Scripts\python.exe" "%HERE%capture_site.py" "%URL%" --out "%OUT%"
echo.
echo Done. Results are in: %OUT%
echo The summary above is also saved as capture\summary.txt
pause
