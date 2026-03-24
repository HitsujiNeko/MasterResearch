@echo off
set "ENV_NAME=masterresearch"

where conda >nul 2>nul
if errorlevel 1 (
  echo Conda not found in PATH. Run this after installing Miniconda/Conda.
  exit /b 1
)

conda run --no-capture-output -n %ENV_NAME% python %*
