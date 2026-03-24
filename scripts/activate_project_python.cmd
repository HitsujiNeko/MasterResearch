@echo off
set "ENV_NAME=masterresearch"

where conda >nul 2>nul
if errorlevel 1 (
  echo Conda not found in PATH. Run this after installing Miniconda/Conda.
  exit /b 1
)

call conda activate %ENV_NAME%
if errorlevel 1 exit /b 1

echo Conda environment activated in this cmd session.
where python
