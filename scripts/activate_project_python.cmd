@echo off
set "PROJECT_ROOT=%~dp0.."
set "VENV_SCRIPTS=%PROJECT_ROOT%\.venv\Scripts"

if not exist "%VENV_SCRIPTS%\python.exe" (
  echo Project Python not found: %VENV_SCRIPTS%\python.exe
  exit /b 1
)

set "PATH=%VENV_SCRIPTS%;%PATH%"
echo Project Python activated in this cmd session.
echo python -> %VENV_SCRIPTS%\python.exe
