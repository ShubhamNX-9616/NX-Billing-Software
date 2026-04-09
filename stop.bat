@echo off
echo Stopping SHUBHAM NX Billing App...
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im cloudflared.exe >nul 2>&1
echo Done. App and tunnel stopped.
pause
