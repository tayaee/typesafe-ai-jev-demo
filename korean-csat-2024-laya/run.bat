@echo off
REM Convenience launcher (Windows): run.bat [csat-laya.ts args...]
REM All arguments are forwarded to src/csat-laya.ts via tsx as-is.
REM
REM Examples:
REM   run.bat --help
REM   run.bat --file csat2024_jev_full.json --subject-id korean --limit 3 --dry-run
REM   run.bat --file csat2024_jev_full.json --subject-id korean
REM
REM Needs: Node.js 20+ and npm. First run does `npm install`.
REM No API key: the Laya model runs locally (weights download once),
REM unless --dry-run is used.
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo ERROR: 'node' not found. Install Node.js 20+.
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: 'npm' not found. Install npm.
  exit /b 1
)
if not exist node_modules (
  echo [run.bat] first run: npm install ...
  call npm install
)
npx tsx src/csat-laya.ts %*
