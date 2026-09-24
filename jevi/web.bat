@echo off
REM jevi launcher (Windows): web.bat <args>
REM   web.bat list-models
REM   web.bat run [--model Qwen/Qwen3.5-2B] [--host 0.0.0.0] [--port 7001] [--hf-token %HF_TOKEN%]
cd /d "%~dp0"
uv run web.py %*
