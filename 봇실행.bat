@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo Cleaning up...
taskkill /F /IM ngrok.exe 2>nul
taskkill /F /IM python.exe 2>nul
ping -n 6 127.0.0.1 >nul

echo Starting bot...
python bot.py

pause
