@echo off
REM ORDELVA command wrapper – runs inside the project's own Python environment
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Run:  powershell -ExecutionPolicy Bypass -File windows\setup.ps1
  exit /b 1
)
".venv\Scripts\python.exe" -m ordelva.cli %*
