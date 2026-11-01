@echo off
chcp 65001 >nul
setlocal disableextensions
setlocal disabledelayedexpansion
title Build Tool Muse Installer
color 0a

echo =====================================================================
echo            TOOL MUSE - DONG GOI FILE CAI DAT (INSTALLER)
echo =====================================================================
echo.

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_installer.ps1" %*
if %errorlevel% neq 0 (
    echo.
    echo [LOI] Qua trinh dong goi that bai!
    pause
    exit /b 1
)

pause
