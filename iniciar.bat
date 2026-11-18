@echo off
cd /d "%~dp0"
py -3 MUUN_RECOVERY_APP.py %*
if errorlevel 1 pause
