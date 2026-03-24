@echo off
set "PROJECT_ROOT=%~dp0.."
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  echo Project Python not found: %PYTHON_EXE%
  exit /b 1
)

"%PYTHON_EXE%" %*
