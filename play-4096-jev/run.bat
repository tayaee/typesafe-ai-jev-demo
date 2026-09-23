@echo off
REM Convenience launcher (Windows): run.bat [play4096.py args...]
REM All arguments are forwarded to play4096.py as-is.
REM
REM Examples:
REM   run.bat --help
REM   run.bat --dry-run --max-moves 2 --start-delay-secs 0 --new-game
REM   run.bat --connect existing-browser-info --url https://thereal4096.github.io --new-game --start-delay-secs 10
REM   run.bat --connect existing-browser-info --shot-dir .\shots
REM
REM Needs: uv (https://docs.astral.sh/uv/getting-started/installation/)
REM API key via --typesafe-api-key KEY, %TYPESAFE_API_KEY%, or .env (see .env.template),
REM unless --dry-run is used.
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo ERROR: 'uv' not found. Install it:
  echo   https://docs.astral.sh/uv/getting-started/installation/
  exit /b 1
)
uv run play4096.py %*
