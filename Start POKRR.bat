@echo off
rem Double-click to start POKRR, then play at http://localhost:8000/play
rem Keep this window open while you play; close it to stop the game.
cd /d "%~dp0"
title POKRR server - keep this window open while playing
start "" http://localhost:8000/play
".venv\Scripts\python.exe" -m uvicorn server.app:app --port 8000
pause
