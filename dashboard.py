"""
dashboard.py
포트폴리오 수익률 인포그래픽 대시보드
  - portfolio.xlsx 읽기
  - KR/US 현재가 조회 (pykrx / yfinance)
  - 수익률 계산
  - HTML 인포그래픽 생성
  - Flask + ngrok HTTPS 서빙
  - 텔레그램 알림 (매일 오전 9시 자동 발송 + 수동 명령)
  - APScheduler 주기적 갱신
"""

import os
import sys
import asyncio
from dotenv import load_dotenv
load_dotenv()
import threading
from datetime import datetime

import pandas as pd
import pytz
from flask import Flask
from price_fetcher import fetch_prices, get_usd_krw
from html_builder import build_html
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
EXCEL_PATH   = "portfolio.xlsx"
NGROK_TOKEN  = os.getenv("NGROK_TOKEN")
TG_TOKEN     = os.getenv("TG_TOKEN")
TG_CHAT_ID   = os.getenv("TG_CHAT_ID")
KST          = pytz.timezone("Asia/Seoul")
SERVER_PORT  = 5050

# 전역 상태
_html_cache  = ""
_dashboard_url = ""
_df_cache: pd.DataFrame = None

# ─────────────────────────────────────────
# 1. 엑셀 읽기
# ─────────────────────────────────────────
def load_portfolio(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="포트폴리오")
    required = {"종목명", "티커", "국가", "비중(%)", "평단가", "통화"}
    missing = required - set(df.columns)
    if missing:
        sys.exit(f"❌ 엑셀에 필수 컬럼이 없습니다: {missing}")
    df["비중(%)"] = pd.to_numeric(df["비중(%)"], errors="coerce").fillna(0)
    df["평단가"]  = pd.to_numeric(df["평단가"],  errors="coerce").fillna(0)
    return df

# ─────────────────────────────────────────
# 3. 텔레그램 메시지 포맷
# ─────────────────────────────────────────
def build_tg_message(df: pd.DataFrame, url: str = "") -> str:
    now = datetime.now(KST).strftime("%Y.%m.%d %H:%M")

    valid = df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
    total_return = 0.0
    if not valid.empty:
        total_return = (valid["비중(%)"] * valid["수익률(%)"]).sum() / valid["비중(%)"].sum()

    sign  = "📈" if total_return >= 0 else "📉"
    arrow = "▲" if total_return >= 0 else "▼"

    lines = [
        f"{sign} *포트폴리오 리포트*",
        f"🕘 {now} (KST)",
        f"",
        f"*가중 평균 수익률: {arrow} {total_return:+.2f}%*",
        f"",
        f"{'종목':<10} {'수익률':>8}",
        "─" * 22,
    ]

    for _, r in df.iterrows():
        ret = r["수익률(%)"]
        if pd.isna(ret):
            ret_str = "  —"
        elif ret > 0:
            ret_str = f"🟢 +{ret:.2f}%"
        elif ret < 0:
            ret_str = f"🔴 {ret:.2f}%"
        else:
            ret_str = f"⚪ 0.00%"
        lines.append(f"`{r['종목명']:<10}` {ret_str}")

    if url:
        lines += ["", f"🔗 [대시보드 열기]({url})"]

    return "\n".join(lines)

async def send_telegram(message: str):
    """텔레그램 메시지 발송"""
    try:
        bot = Bot(token=TG_TOKEN)
        await bot.send_message(
            chat_id=TG_CHAT_ID,
            text=message,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        print("  ✅ 텔레그램 발송 완료")
    except Exception as e:
        print(f"  ⚠️  텔레그램 발송 실패: {e}")

def send_telegram_sync(message: str):
    asyncio.run(send_telegram(message))

# ─────────────────────────────────────────
# 4. 스케줄 작업 (매일 09:00 KST)
# ─────────────────────────────────────────
def scheduled_report():
    global _html_cache, _df_cache
    print(f"\n[⏰ 스케줄] {datetime.now(KST).strftime('%H:%M')} 자동 리포트 생성 중...")
    try:
        df = load_portfolio(EXCEL_PATH)
        df = fetch_prices(df)
        _df_cache  = df
        _html_cache = build_html(df)
        msg = build_tg_message(df, _dashboard_url)
        send_telegram_sync(msg)
        print("  → 스케줄 리포트 완료")
    except Exception as e:
        print(f"  ⚠️  스케줄 리포트 오류: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler(timezone=KST)
    # 매일 오전 9시
    scheduler.add_job(scheduled_report, "cron", hour=9, minute=0, id="morning_report")
    # 매일 오후 4시 (장 마감 후)
    scheduler.add_job(scheduled_report, "cron", hour=16, minute=0, id="closing_report")
    scheduler.start()
    print("  ⏰ 스케줄러 시작 (매일 09:00 / 16:00 KST 자동 발송)")
    return scheduler

# ─────────────────────────────────────────
# 5. 텔레그램 봇 명령어
# ─────────────────────────────────────────
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/report  →  즉시 수익률 리포트 발송"""
    await update.message.reply_text("📊 포트폴리오 조회 중...")
    try:
        df = load_portfolio(EXCEL_PATH)
        df = fetch_prices(df)
        global _df_cache, _html_cache
        _df_cache   = df
        _html_cache = build_html(df)
        msg = build_tg_message(df, _dashboard_url)
        await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {e}")

async def cmd_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/url  →  대시보드 URL 발송"""
    if _dashboard_url:
        await update.message.reply_text(f"🌐 대시보드: {_dashboard_url}")
    else:
        await update.message.reply_text("⚠️ 서버가 아직 시작되지 않았습니다.")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help  →  명령어 목록"""
    await update.message.reply_text(
        "📋 *사용 가능한 명령어*\n\n"
        "/report — 현재 수익률 즉시 조회\n"
        "/url    — 대시보드 URL 확인\n"
        "/help   — 명령어 도움말\n\n"
        "⏰ 자동 발송: 매일 09:00 / 16:00 (KST)",
        parse_mode="Markdown"
    )

def start_telegram_bot():
    """텔레그램 봇을 별도 스레드에서 실행"""
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = Application.builder().token(TG_TOKEN).build()
        app.add_handler(CommandHandler("report", cmd_report))
        app.add_handler(CommandHandler("url",    cmd_url))
        app.add_handler(CommandHandler("help",   cmd_help))
        print("  🤖 텔레그램 봇 시작 (/report, /url, /help)")
        app.run_polling(stop_signals=None)

    t = threading.Thread(target=run, daemon=True)
    t.start()

# ─────────────────────────────────────────
# 6. Flask + ngrok 서버
# ─────────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return _html_cache

def run_server(html: str, port: int = SERVER_PORT):
    global _html_cache, _dashboard_url
    _html_cache = html

    if NGROK_TOKEN:
        from pyngrok import ngrok, conf
        conf.get_default().auth_token = NGROK_TOKEN
        tunnel = ngrok.connect(port, "http")
        _dashboard_url = tunnel.public_url.replace("http://", "https://")
        print(f"\n{'='*55}")
        print(f"  🌐  대시보드 URL (HTTPS): {_dashboard_url}")
        print(f"{'='*55}\n")
    else:
        _dashboard_url = f"http://localhost:{port}"
        print(f"\n  ⚠️  NGROK_TOKEN 미설정 → 로컬만 접속 가능")
        print(f"  🌐  로컬 URL: {_dashboard_url}\n")

    flask_app.run(port=port, use_reloader=False)

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  📊  포트폴리오 대시보드 시작")
    print("=" * 55)

    print(f"\n[1/4] 엑셀 로딩: {EXCEL_PATH}")
    df = load_portfolio(EXCEL_PATH)
    print(f"  → {len(df)}개 종목 로드 완료")

    print("\n[2/4] 현재가 조회 중...")
    df = fetch_prices(df)
    _df_cache = df
    print("  → 가격 조회 완료")

    print("\n[3/4] 텔레그램 봇 + 스케줄러 시작...")
    start_telegram_bot()
    start_scheduler()

    print("\n[4/4] 대시보드 생성 및 서버 시작...")
    html = build_html(df)

    # 터미널 수익률 미리보기
    valid = df[df["수익률(%)"].notna()]
    print("\n  ┌─────────────────────────────────────────────┐")
    for _, r in valid.iterrows():
        sign = "+" if r["수익률(%)"] > 0 else ""
        print(f"  │  {r['종목명']:<12}  {sign}{r['수익률(%)']:.2f}%")
    print("  └─────────────────────────────────────────────┘")

    # 시작 알림 발송
    msg = "🚀 *포트폴리오 대시보드 시작*\n\n" + build_tg_message(df)
    threading.Thread(target=send_telegram_sync, args=(msg,), daemon=True).start()

    run_server(html)
