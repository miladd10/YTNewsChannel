@echo off
cd /d "%~dp0"
py.exe -3 scripts\start_windows.py 2>nul
if errorlevel 1 python.exe scripts\start_windows.py
pause
