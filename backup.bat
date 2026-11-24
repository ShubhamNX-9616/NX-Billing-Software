@echo off
rem Back up both databases and the photos. Run by hand, or schedule it with
rem Windows Task Scheduler (see APPLICATION_GUIDE.md, section 6).
rem Set BACKUP_DIR in .env to save to another drive or a synced folder.
cd /d "%~dp0"
python scripts\backup.py
if errorlevel 1 (
    echo.
    echo BACKUP FAILED - see the message above.
    pause
    exit /b 1
)
