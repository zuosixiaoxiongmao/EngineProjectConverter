@echo off
cd /d "%~dp0"
python engine_converter.py %*
if errorlevel 1 pause
