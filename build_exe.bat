@echo off
REM ============================================
REM FISCALINK Build Script
REM ============================================
echo.
echo ============================================
echo   FISCALINK EXE Builder
echo ============================================
echo.

echo Installing required dependencies...
pip install pyinstaller pystray plyer Pillow pdfplumber PyMuPDF reportlab qrcode cryptography requests flasgger dash dash-bootstrap-components plotly

echo.
echo Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist FISCALINK.spec del /q FISCALINK.spec

echo.
echo Building EXE (this may take 5-10 minutes)...
echo.
REM Build using the spec file
pyinstaller build.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo ============================================
    echo   BUILD FAILED!
    echo ============================================
    echo Check the error messages above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   BUILD SUCCESSFUL!
echo ============================================
echo.
echo Your EXE file is located at:
echo   dist\FISCALINK.exe
echo.
echo IMPORTANT POST-BUILD STEPS:
echo   1. Copy your 'assets' folder into 'dist\FISCALINK\'
echo   2. Ensure your certificates are in 'C:\certs\' 
echo      (client_cert.pem and client_key.key)
echo   3. Double-click dist\FISCALINK.exe to run!
echo.
pause