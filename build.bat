@echo off
title Build Muse AI Tool Installer
chcp 65001 >nul

echo ======================================================================
echo          MUSE AI TOOL - TIEN TRINH DONG GOI CAI DAT .EXE
echo ======================================================================
echo.

echo [1/3] Kiem tra moi truong Python va PyInstaller...
python --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python! Vui long cai dat Python 3.10+
    pause
    exit /b 1
)

echo [2/3] Dang dong goi ma nguon bang PyInstaller...
pyinstaller --clean -y muse_app.spec
if errorlevel 1 (
    echo [LOI] Qua trinh PyInstaller that bai!
    pause
    exit /b 1
)

echo [3/3] Dang bien dich file cai dat bang Inno Setup...
set "ISCC_PATH="
if exist "C:\Users\vuive\AppData\Local\Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe" (
    set "ISCC_PATH=C:\Users\vuive\AppData\Local\Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe"
) else if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"
) else (
    for /f "delims=" %%i in ('where iscc 2^>nul') do set "ISCC_PATH=%%i"
)

if "%ISCC_PATH%"=="" (
    echo [CANH BAO] Khong tim thay ISCC.exe de tao file Setup.
    echo Ban co the chay file MuseAITool.exe truc tiep trong thu muc dist\MuseAITool\
    pause
    exit /b 0
)

"%ISCC_PATH%" installer.iss
if errorlevel 1 (
    echo [LOI] Bien dich Inno Setup that bai!
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo    THANH CONG! File cai dat da san sang tai:
echo    installer_output\MuseAITool_v1.0_Setup.exe
echo ======================================================================
echo.
pause
