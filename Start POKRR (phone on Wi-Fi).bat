@echo off
rem Start POKRR so phones on the SAME Wi-Fi can play too.
rem Keep this window open while you play; close it to stop the game.
rem Use this only on your home Wi-Fi (not public Wi-Fi).
cd /d "%~dp0"
title POKRR (Wi-Fi) - keep this window open while playing
for /f %%i in ('".venv\Scripts\python.exe" -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('10.255.255.255',1));print(s.getsockname()[0])"') do set IP=%%i
echo.
echo   ==============================================================
echo     On your phone (same Wi-Fi), open:   http://%IP%:8000
echo     On this laptop you can still use:   http://localhost:8000/play
echo   ==============================================================
echo     If Windows asks about the firewall, allow "Private networks".
echo.
start "" http://localhost:8000/play
".venv\Scripts\python.exe" -m uvicorn server.app:app --host 0.0.0.0 --port 8000
pause
