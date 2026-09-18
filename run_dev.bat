@echo off
echo ============================================
echo   FISCALINK Development Runner
echo ============================================
echo.
echo Starting FISCALINK in development mode...
echo - Flask API: http://localhost:5000
echo - Dashboard: http://localhost:8050
echo - Receipt Processor: Monitoring C:\Receipt
echo.
echo A system tray icon will appear near your clock.
echo Press Ctrl+C in this window to stop the system.
echo ============================================
echo.

REM Activate virtual environment if it exists (optional)
if exist "myenv\Scripts\activate.bat" (
    call myenv\Scripts\activate.bat
)

REM Run the tray application
python tray_app.py

pause