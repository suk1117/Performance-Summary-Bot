"""
bot.py  ─  포트폴리오 대시보드 텔레그램 봇
────────────────────────────────────────────
명령어
  /시작       가격 조회 + 대시보드 생성 + URL 전송
  /종료       대시보드 서버 종료
  /portfolio  마지막 대시보드 URL 재전송
  /refresh    가격 재조회 후 새 URL 전송
  /summary    텍스트 수익률 요약
  /help       사용법 안내

자동 스케줄 (/시작 이후에만 동작)
  15:35 KST  KR 장 마감 후 자동 전송
  07:00 KST  US 장 마감 후 자동 전송
────────────────────────────────────────────
"""

import io
import os
import asyncio
from dotenv import load_dotenv
load_dotenv()
import threading
import logging
from datetime import datetime

import pandas as pd
import pytz
from flask import Flask
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters,
)
from telegram.constants import ParseMode

from price_fetcher import fetch_prices
from html_builder import build_html

# ══════════════════════════════════════════
# 설정
# ══════════════════════════════════════════
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
NGROK_TOKEN      = os.getenv("NGROK_TOKEN")
EXCEL_PATH       = "portfolio.xlsx"
FLASK_PORT       = 5050
KST              = pytz.timezone("Asia/Seoul")
# ══════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── 전역 상태 ──
app_flask   = Flask(__name__)
_flask_thread = None
_tunnel       = None
_started      = False   # /시작 후 True

_state = {
    "html":        "",
    "df":          None,
    "public_url":  "",
    "last_update": None,
}

REQUIRED_COLS = {"종목명", "티커", "국가", "비중(%)", "평단가", "통화"}


# ────────────────────────────────────────
# 엑셀 파싱
# ────────────────────────────────────────
def parse_excel_file(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="포트폴리오")
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing}")
    df["비중(%)"] = pd.to_numeric(df["비중(%)"], errors="coerce").fillna(0)
    df["평단가"]  = pd.to_numeric(df["평단가"],  errors="coerce").fillna(0)
    return df

def parse_excel_bytes(data: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(data), sheet_name="포트폴리오")
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing}")
    df["비중(%)"] = pd.to_numeric(df["비중(%)"], errors="coerce").fillna(0)
    df["평단가"]  = pd.to_numeric(df["평단가"],  errors="coerce").fillna(0)
    return df


# ────────────────────────────────────────
# 대시보드 빌드 / 갱신
# ────────────────────────────────────────
def build_dashboard(df_raw: pd.DataFrame) -> pd.DataFrame:
    df   = fetch_prices(df_raw)
    html = build_html(df)
    _state["df"]          = df
    _state["html"]        = html
    _state["last_update"] = datetime.now(KST)
    return df

def refresh_dashboard() -> pd.DataFrame:
    if _state["df"] is None:
        raise RuntimeError("먼저 /시작 또는 엑셀 파일을 전송해 주세요.")
    df_raw = _state["df"].drop(
        columns=[c for c in ["현재가", "수익률(%)", "USD_KRW"] if c in _state["df"].columns]
    )
    return build_dashboard(df_raw)


# ────────────────────────────────────────
# Flask + ngrok
# ────────────────────────────────────────
@app_flask.route("/")
def index():
    return _state["html"] or "<h2>대기 중 — /시작 명령어를 입력하세요</h2>"

def _run_flask():
    import logging as _lg
    _lg.getLogger("werkzeug").setLevel(_lg.ERROR)
    app_flask.run(port=FLASK_PORT, use_reloader=False)

def start_server() -> str:
    global _flask_thread, _tunnel

    if _flask_thread is None or not _flask_thread.is_alive():
        _flask_thread = threading.Thread(target=_run_flask, daemon=True)
        _flask_thread.start()

    if _tunnel is None:
        from pyngrok import ngrok as _ngrok, conf as _conf
        _conf.get_default().auth_token = NGROK_TOKEN
        _tunnel = _ngrok.connect(FLASK_PORT, "http")

    url = _tunnel.public_url.replace("http://", "https://")
    _state["public_url"] = url
    return url


# ────────────────────────────────────────
# 텍스트 요약
# ────────────────────────────────────────
def _summary_text(df: pd.DataFrame) -> str:
    ts  = _state["last_update"].strftime("%m/%d %H:%M") if _state["last_update"] else "—"
    url = _state["public_url"]

    lines = [f"포트폴리오 요약 | {ts} KST\n"]

    valid = df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
    if not valid.empty:
        total = (valid["비중(%)"] * valid["수익률(%)"]).sum() / valid["비중(%)"].sum()
        arrow = "▲" if total >= 0 else "▼"
        lines.append(f"*가중 평균 수익률: {arrow} {'+' if total>=0 else ''}{total:.2f}%*\n")

    lines.append("```")
    lines.append(f"{'종목':<10} {'비중':>5} {'수익률':>8}")
    lines.append("─" * 26)
    for _, r in df.iterrows():
        ret = r["수익률(%)"]
        ret_str = "   —  " if pd.isna(ret) else f"{'+' if ret>=0 else ''}{ret:.2f}%"
        lines.append(f"{r['종목명']:<10} {r['비중(%)']:>4.1f}% {ret_str:>8}")
    lines.append("```")
    if url:
        lines.append(f"\n[대시보드 열기]({url})")
    return "\n".join(lines)


# ────────────────────────────────────────
# 명령어 핸들러
# ────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/시작 → 엑셀 읽기 + 가격 조회 + 대시보드 생성"""
    global _started
    msg = await update.message.reply_text("대시보드 시작 중... (30초~1분 소요)")

    try:
        # 서버 먼저 띄우기
        url = await asyncio.get_event_loop().run_in_executor(None, start_server)

        # 엑셀 로드
        if not os.path.exists(EXCEL_PATH):
            await msg.edit_text(
                f"portfolio.xlsx 파일이 없습니다.\n"
                f"이 채팅에 .xlsx 파일을 전송해 주세요."
            )
            return

        df_raw = await asyncio.get_event_loop().run_in_executor(None, parse_excel_file, EXCEL_PATH)
        await msg.edit_text("가격 조회 중...")

        df = await asyncio.get_event_loop().run_in_executor(None, build_dashboard, df_raw)
        _started = True

        await msg.edit_text(
            _summary_text(df),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
        )
        log.info("/시작 완료")

    except Exception as e:
        log.error(f"/시작 오류: {e}")
        await msg.edit_text(f"오류 발생: {e}")


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/종료 → ngrok 터널 닫기"""
    global _tunnel, _started
    if _tunnel is None:
        await update.message.reply_text("현재 실행 중인 대시보드가 없습니다.")
        return
    try:
        from pyngrok import ngrok as _ngrok
        _ngrok.disconnect(_tunnel.public_url)
        _tunnel   = None
        _started  = False
        _state["public_url"] = ""
        await update.message.reply_text("대시보드가 종료되었습니다.\n다시 시작하려면 /시작")
    except Exception as e:
        await update.message.reply_text(f"종료 오류: {e}")


async def cmd_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _state["public_url"]:
        await update.message.reply_text("/시작 명령어로 먼저 대시보드를 켜세요.")
        return
    ts  = _state["last_update"].strftime("%m/%d %H:%M")
    url = _state["public_url"]
    await update.message.reply_text(
        f"*포트폴리오 대시보드*\n\n기준: `{ts} KST`\n{url}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if _state["df"] is None:
        await update.message.reply_text("/시작 명령어로 먼저 대시보드를 켜세요.")
        return
    msg = await update.message.reply_text("가격 재조회 중...")
    try:
        df = await asyncio.get_event_loop().run_in_executor(None, refresh_dashboard)
        await msg.edit_text(
            _summary_text(df),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
        )
    except Exception as e:
        await msg.edit_text(f"오류: {e}")


async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if _state["df"] is None:
        await update.message.reply_text("/시작 명령어로 먼저 대시보드를 켜세요.")
        return
    await update.message.reply_text(
        _summary_text(_state["df"]),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*명령어 목록*\n\n"
        "/on        — 가격 조회 + 대시보드 생성\n"
        "/off       — 대시보드 서버 종료\n"
        "/portfolio — 대시보드 URL 재전송\n"
        "/refresh   — 가격 재조회\n"
        "/summary   — 텍스트 수익률 요약\n"
        "/help      — 도움말\n\n"
        "또는 .xlsx 파일을 전송하면 자동 분석됩니다.\n\n"
        "자동 알림: 평일 15:35 (KR) / 07:00 (US)",
        parse_mode=ParseMode.MARKDOWN,
    )


# ────────────────────────────────────────
# 파일 수신 핸들러
# ────────────────────────────────────────
async def handle_excel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc   = update.message.document
    fname = doc.file_name or ""

    if not fname.endswith(".xlsx"):
        await update.message.reply_text(".xlsx 파일만 지원합니다.")
        return

    msg = await update.message.reply_text("파일 수신 중...")
    try:
        file = await ctx.bot.get_file(doc.file_id)
        buf  = await file.download_as_bytearray()
        await msg.edit_text("가격 조회 중... (30초~1분 소요)")

        url    = await asyncio.get_event_loop().run_in_executor(None, start_server)
        df_raw = parse_excel_bytes(bytes(buf))
        df     = await asyncio.get_event_loop().run_in_executor(None, build_dashboard, df_raw)

        await msg.edit_text(
            _summary_text(df),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
        )
    except ValueError as e:
        await msg.edit_text(f"엑셀 형식 오류: {e}")
    except Exception as e:
        log.error(f"handle_excel 오류: {e}")
        await msg.edit_text(f"오류 발생: {e}")


# ────────────────────────────────────────
# 자동 스케줄
# ────────────────────────────────────────
async def scheduled_send(label: str):
    if not _started or _state["df"] is None:
        return
    log.info(f"자동 전송 시작 ({label})")
    try:
        df  = await asyncio.get_event_loop().run_in_executor(None, refresh_dashboard)
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"*{label} 자동 업데이트*\n\n{_summary_text(df)}",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"자동 전송 실패: {e}")


# ────────────────────────────────────────
# MAIN
# ────────────────────────────────────────
async def post_init(app):
    scheduler = AsyncIOScheduler(timezone=KST)
    scheduler.add_job(
        scheduled_send, "cron",
        day_of_week="mon-fri", hour=15, minute=35,
        kwargs={"label": "KR 장 마감"},
    )
    scheduler.add_job(
        scheduled_send, "cron",
        day_of_week="tue-sat", hour=7, minute=0,
        kwargs={"label": "US 장 마감"},
    )
    scheduler.start()
    log.info("스케줄러 시작 (평일 15:35 KR / 07:00 US)")


def main():
    log.info("=" * 45)
    log.info("  포트폴리오 봇 대기 중")
    log.info("  텔레그램에서 /on 을 입력하세요")
    log.info("=" * 45)

    tg_app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    tg_app.add_handler(CommandHandler("on",        cmd_start))
    tg_app.add_handler(CommandHandler("off",       cmd_stop))
    tg_app.add_handler(CommandHandler("start",     cmd_start))
    tg_app.add_handler(CommandHandler("help",      cmd_help))
    tg_app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    tg_app.add_handler(CommandHandler("refresh",   cmd_refresh))
    tg_app.add_handler(CommandHandler("summary",   cmd_summary))
    tg_app.add_handler(MessageHandler(filters.Document.ALL, handle_excel))

    tg_app.run_polling()


if __name__ == "__main__":
    main()
