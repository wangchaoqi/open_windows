@echo off
setlocal
cd /d "%~dp0"
title Build Window Switcher EXE

echo ==============================================
echo  Building Window Switcher EXE
echo ==============================================
echo.

set "PYTHON="

REM Find Python with tkinter
where python >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        "%%i" -c "import tkinter" >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON=%%i"
            goto :found
        )
    )
)

for %%v in (313 312 311 310 39 38) do (
    for %%d in (
        "%LOCALAPPDATA%\Programs\Python\Python%%v"
        "C:\Python%%v"
        "%PROGRAMFILES%\Python%%v"
    ) do (
        if exist "%%~d\python.exe" (
            "%%~d\python.exe" -c "import tkinter" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON=%%~d\python.exe"
                goto :found
            )
        )
    )
)

echo [ERROR] No Python with tkinter found.
echo Install Python 3.8+ from https://www.python.org/downloads/
pause
exit /b 1

:found
echo [OK] Python: %PYTHON%
echo.

echo [1/3] Installing Nuitka...
"%PYTHON%" -m pip install nuitka --quiet
echo [OK]
echo.

echo [2/3] Building EXE (5-10 minutes)...
"%PYTHON%" -m nuitka --standalone --onefile --windows-disable-console --enable-plugin=tk-inter --output-dir=dist --output-filename=WindowSwitcher.exe window_switcher.pyw

if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo [3/3] Done: dist\WindowSwitcher.exe
echo.
echo You can run it without Python now.
pause
