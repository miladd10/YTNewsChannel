@echo off
cd /d "%~dp0"
if exist data\server.pid (
  set /p PID=<data\server.pid
  taskkill /PID %PID% /T /F >nul 2>&1
  del /q data\server.pid >nul 2>&1
)
echo YT News Studio stopped.
pause
