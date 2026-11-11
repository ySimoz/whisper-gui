@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo Whisper GUI - Windows Automated Setup and Launcher
echo ===================================================

cd /d "%~dp0"

:: 1. Check Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10, 3.11, or 3.12 from python.org or Microsoft Store.
    pause
    exit /b 1
)

:: 2. Check FFmpeg
where ffmpeg >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [WARNING] FFmpeg was not detected in PATH.
    echo Whisper GUI requires FFmpeg for audio processing and slicing.
    echo You can install it via: winget install Gyan.FFmpeg
    echo or via Chocolatey: choco install ffmpeg
    echo.
)

:: 3. Setup Virtual Environment
if not exist ".venv" (
    echo [INFO] Creating virtual environment (.venv)...
    python -m venv .venv
    set NEED_INSTALL=1
)

call .venv\Scripts\activate.bat

if defined NEED_INSTALL (
    echo [INFO] Upgrading pip and installing dependencies...
    python -m pip install --upgrade pip
    pip install -e .
) else (
    pip check >nul 2>nul
    if %ERRORLEVEL% neq 0 (
        echo [INFO] Syncing dependencies...
        pip install -e .
    )
)

:: 4. Launch Whisper GUI
echo [INFO] Launching Whisper GUI...
python main.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Application exited with error code %ERRORLEVEL%.
    pause
)
