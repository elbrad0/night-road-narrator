@echo off
title Night Road Voice Launcher
cd /d "%~dp0"

echo ============================================
echo    Night Road - voice narration launcher
echo ============================================
echo.

echo [1/3] Starting the voice pipeline...
start "Night Road Pipeline" cmd /k py nightroad.py
echo       (left running in its own window)
timeout /t 4 /nobreak >nul

echo [2/3] Launching Night Road through Steam...
start "" "steam://rungameid/1290270"
echo       waiting for the game to load...
timeout /t 12 /nobreak >nul

echo [3/3] Injecting the watcher (in its own window)...
start "Night Road Inject" cmd /k py inject.py

echo.
echo Launcher done. Check the "Night Road Inject" window for the result.
echo This window closes by itself in a few seconds.
timeout /t 6 /nobreak >nul
