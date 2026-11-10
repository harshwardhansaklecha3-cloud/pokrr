@echo off
rem POKRR online: the game + a free Cloudflare link for friends.
rem Keep the window open while you play; close it to stop.
title POKRR online
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\online.ps1"
echo.
echo  POKRR online has stopped. You can close this window.
pause >nul
