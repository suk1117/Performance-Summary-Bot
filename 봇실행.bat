@echo off
chcp 65001 > nul
cd /d "%~dp0"

set SERVER=suk03180s@34.58.101.60
set SERVICE=portfolio-bot

echo [1/3] 서버 봇 중지 중...
ssh %SERVER% "sudo systemctl stop %SERVICE%"
if %errorlevel% neq 0 (
    echo ⚠️  서버 봇 중지 실패. 계속 진행합니다.
)

echo [2/3] 로컬 봇 시작...
python run_bot.py

echo [3/3] 서버 봇 재시작 중...
ssh %SERVER% "sudo systemctl start %SERVICE%"
if %errorlevel% neq 0 (
    echo ⚠️  서버 봇 재시작 실패. 수동으로 실행하세요:
    echo     ssh %SERVER% "sudo systemctl start %SERVICE%"
) else (
    echo ✅ 서버 봇 재시작 완료
)

pause
