@echo off
REM -----------------------------------------------------------------------
REM  Up Front Shop — one-shot Windows build script.
REM
REM  Produces:
REM      dist\UpFrontShop\UpFrontShop.exe   (portable app folder)
REM      dist\UpFrontShopSetup.exe          (Windows installer)
REM
REM  Requirements (install once on the build PC):
REM      - Python 3.11 or 3.12 (64-bit) on PATH
REM      - Inno Setup 6 installed at the default location
REM      - Internet access the first time (pip installs dependencies)
REM
REM  Usage:  double-click this file, or from a command prompt:
REM              cd upfront-shop
REM              build\build.bat
REM -----------------------------------------------------------------------
setlocal
cd /d "%~dp0\.."

echo.
echo === [1/4] Create/refresh venv =================================
if not exist .venv (
    py -3 -m venv .venv
)
call .venv\Scripts\activate.bat

echo.
echo === [2/4] Install build requirements ==========================
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller==6.9.0

echo.
echo === [3/4] PyInstaller build ===================================
if exist dist\UpFrontShop rmdir /s /q dist\UpFrontShop
pyinstaller --clean --noconfirm build\upfront.spec
if errorlevel 1 goto :fail

echo.
echo === [4/4] Inno Setup installer ================================
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo WARNING: Inno Setup 6 not found at:
    echo     %ISCC%
    echo The app was built under dist\UpFrontShop but the .exe installer
    echo was NOT produced. Install Inno Setup 6 from https://jrsoftware.org
    echo and re-run this script to generate UpFrontShopSetup.exe.
    goto :done
)
"%ISCC%" build\installer.iss
if errorlevel 1 goto :fail

:done
echo.
echo === Build complete. ===========================================
echo Portable app folder:  dist\UpFrontShop\
echo Windows installer:    dist\UpFrontShopSetup.exe
echo.
pause
goto :eof

:fail
echo.
echo !!! Build failed — see messages above.
pause
exit /b 1
