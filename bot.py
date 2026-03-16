"""
bot.py  ─  포트폴리오 대시보드 텔레그램 봇 (멀티유저)
────────────────────────────────────────────────────
사용법
  텔레그램에서 .xlsx 파일 전송
  → 자동으로 가격 조회 + 대시보드 생성
  → 메인 URL(/) 에서 유저 선택 → /user/<id> 개별 대시보드

명령어
  /portfolio  본인 대시보드 URL 전송
  /refresh    가격 재조회
  /summary    텍스트 수익률 요약
  /help       사용법

자동 스케줄 (KST)
  15:35  KR 장 마감
  07:00  US 장 마감
────────────────────────────────────────────────────
"""

import io
import os
import sys
import asyncio
import threading
import logging

# Windows cp949 환경에서 이모지 print 오류 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import pytz
from flask import Flask, abort
from pyngrok import ngrok, conf as ngrok_conf
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters,
)
from telegram.constants import ParseMode

from price_fetcher import fetch_prices
from html_builder import build_index_html, build_user_html

# ══════════════════════════════════════════
# 설정
# ══════════════════════════════════════════
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
NGROK_TOKEN      = os.getenv("NGROK_TOKEN")
FLASK_PORT       = 5050
KST              = pytz.timezone("Asia/Seoul")
# ══════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S", level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── 전역 상태 ──
# users[user_id] = { "name", "last_update", "df" }
users: dict = {}
public_url: str = ""

app_flask = Flask(__name__)
REQUIRED_COLS = {"종목명", "국가", "비중(%)", "평단가", "통화"}


# ────────────────────────────────────────
# Flask 라우트
# ────────────────────────────────────────
@app_flask.route("/")
def index():
    return build_index_html(users)

@app_flask.route("/user/<int:uid>")
def user_page(uid: int):
    if uid not in users:
        abort(404)
    u = users[uid]
    return build_user_html(u["df"], display_name=u.get("name", ""), all_users=users, current_uid=uid)

def run_flask():
    app_flask.run(port=FLASK_PORT, use_reloader=False)


# ────────────────────────────────────────
# ngrok
# ────────────────────────────────────────
def start_ngrok() -> str:
    global public_url
    ngrok_conf.get_default().auth_token = NGROK_TOKEN
    tunnel = ngrok.connect(FLASK_PORT, "http")
    public_url = tunnel.public_url.replace("http://", "https://")
    log.info(f"🌐 ngrok URL: {public_url}")
    return public_url


# ────────────────────────────────────────
# 엑셀 파싱
# ────────────────────────────────────────
def parse_excel(data: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(data), sheet_name="포트폴리오")
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing}")
    df["비중(%)"] = pd.to_numeric(df["비중(%)"], errors="coerce").fillna(0)
    df["평단가"]  = pd.to_numeric(df["평단가"],  errors="coerce").fillna(0)
    return df


# ────────────────────────────────────────
# 가격 조회
# ────────────────────────────────────────
def build_dashboard_for(uid: int) -> pd.DataFrame:
    """users[uid] 기준으로 가격 재조회 후 df 갱신"""
    df_raw = users[uid]["df"].drop(
        columns=[c for c in ["현재가", "수익률(%)", "USD_KRW"] if c in users[uid]["df"].columns]
    )
    df = fetch_prices(df_raw)
    users[uid]["df"]          = df
    users[uid]["last_update"] = datetime.now(KST)
    return df


# ────────────────────────────────────────
# 텍스트 요약
# ────────────────────────────────────────
def _summary_text(uid: int) -> str:
    u   = users[uid]
    df  = u["df"]
    ts  = u["last_update"].strftime("%m/%d %H:%M") if u["last_update"] else "—"
    url = f"{public_url}/user/{uid}"

    lines = [f"📊 *{u.get('name','포트폴리오')} 요약* `{ts} KST`\n"]

    valid = df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
    if not valid.empty:
        total = (valid["비중(%)"] * valid["수익률(%)"]).sum() / valid["비중(%)"].sum()
        emoji = "🟢" if total >= 0 else "🔴"
        lines.append(f"{emoji} *가중 평균 수익률: {'+' if total>=0 else ''}{total:.2f}%*\n")

    lines.append("```")
    lines.append(f"{'종목':<10} {'비중':>5} {'수익률':>8}")
    lines.append("─" * 26)
    for _, r in df.iterrows():
        ret = r["수익률(%)"]
        ret_str = "   —  " if pd.isna(ret) else f"{'+' if ret>=0 else ''}{ret:.2f}%"
        lines.append(f"{r['종목명']:<10} {r['비중(%)']:>4.1f}% {ret_str:>8}")
    lines.append("```")
    lines.append(f"\n🔗 [내 대시보드]({url})")
    return "\n".join(lines)


# ────────────────────────────────────────
# 파일 수신 핸들러
# ────────────────────────────────────────
async def handle_excel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc   = update.message.document
    fname = doc.file_name or ""
    uid   = update.effective_user.id
    uname = (update.effective_user.full_name
             or update.effective_user.username
             or f"User {uid}")

    if not fname.endswith(".xlsx"):
        await update.message.reply_text(
            "⚠️ .xlsx 파일만 지원합니다.", parse_mode=ParseMode.MARKDOWN
        )
        return

    msg = await update.message.reply_text("📥 파일 수신 중...")

    try:
        file = await ctx.bot.get_file(doc.file_id)
        buf  = await file.download_as_bytearray()
        await msg.edit_text("🔍 가격 조회 중... (30초~1분 소요)")

        df_raw = parse_excel(bytes(buf))

        # users 초기 등록 (이름 보존)
        if uid not in users:
            users[uid] = {"name": uname, "last_update": None, "df": df_raw}
        else:
            users[uid]["df"] = df_raw  # raw 저장 후 build_dashboard_for 에서 fetch

        df = await asyncio.get_event_loop().run_in_executor(
            None, build_dashboard_for, uid
        )

        ts      = users[uid]["last_update"].strftime("%m/%d %H:%M")
        summary = _summary_text(uid)

        await msg.edit_text(
            f"✅ *분석 완료* `{ts} KST`\n\n{summary}",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
        )
        log.info(f"✅ {uname}({uid}) 처리 완료")

    except ValueError as e:
        await msg.edit_text(
            f"❌ 엑셀 형식 오류\n`{e}`\n\n필수컬럼: 종목명, 티커, 국가, 비중(%), 평단가, 통화\n시트명: 포트폴리오",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        log.error(f"handle_excel 오류: {e}")
        await msg.edit_text(f"❌ 처리 중 오류\n`{e}`", parse_mode=ParseMode.MARKDOWN)


# ────────────────────────────────────────
# 커맨드 핸들러
# ────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *사용법*\n\n"
        "1️⃣ `.xlsx` 파일을 이 채팅에 전송\n"
        "   → 수익률 분석 + 대시보드 URL 제공\n\n"
        "2️⃣ 명령어\n"
        "  `/portfolio` — 내 대시보드 URL\n"
        "  `/refresh`   — 가격 재조회\n"
        "  `/summary`   — 텍스트 요약\n\n"
        "3️⃣ 자동 알림\n"
        "  🇰🇷 KST 15:35 / 🇺🇸 KST 07:00\n\n"
        "📎 컬럼: 종목명 / 티커 / 국가(KR·US·현금) / 비중(%) / 평단가 / 통화(KRW·USD)",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in users:
        await update.message.reply_text("⚠️ 먼저 .xlsx 파일을 전송해 주세요.")
        return
    ts  = users[uid]["last_update"].strftime("%m/%d %H:%M")
    url = f"{public_url}/user/{uid}"
    await update.message.reply_text(
        f"📊 *내 대시보드*\n\n🕐 기준: `{ts} KST`\n🔗 {url}",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in users:
        await update.message.reply_text("⚠️ 먼저 .xlsx 파일을 전송해 주세요.")
        return
    msg = await update.message.reply_text("🔄 가격 재조회 중...")
    try:
        await asyncio.get_event_loop().run_in_executor(None, build_dashboard_for, uid)
        ts  = users[uid]["last_update"].strftime("%m/%d %H:%M")
        url = f"{public_url}/user/{uid}"
        await msg.edit_text(
            f"✅ *업데이트 완료*\n\n🕐 `{ts} KST`\n🔗 {url}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await msg.edit_text(f"❌ 오류: {e}")

async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in users:
        await update.message.reply_text("⚠️ 먼저 .xlsx 파일을 전송해 주세요.")
        return
    await update.message.reply_text(
        _summary_text(uid),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


# ────────────────────────────────────────
# 자동 스케줄
# ────────────────────────────────────────
async def scheduled_send(label: str):
    if not users:
        log.info(f"⏰ {label} — 유저 없음, 건너뜀")
        return
    log.info(f"⏰ 자동 전송 시작 ({label})")
    bot = Bot(token=TELEGRAM_TOKEN)
    for uid in list(users.keys()):
        try:
            await asyncio.get_event_loop().run_in_executor(None, build_dashboard_for, uid)
            text = f"⏰ *{label} 자동 업데이트*\n\n{_summary_text(uid)}"
            await bot.send_message(
                chat_id=uid,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            log.info(f"  → {users[uid].get('name')}({uid}) 전송 완료")
        except Exception as e:
            log.error(f"  → {uid} 전송 실패: {e}")


# ────────────────────────────────────────
# MAIN
# ────────────────────────────────────────
def main():
    log.info("=" * 55)
    log.info("  📊  포트폴리오 봇 시작 (멀티유저)")
    log.info("=" * 55)

    threading.Thread(target=run_flask, daemon=True).start()
    log.info(f"  🖥️  Flask 서버 시작 (port {FLASK_PORT})")

    start_ngrok()

    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(CommandHandler("start",     cmd_help))
    tg_app.add_handler(CommandHandler("help",      cmd_help))
    tg_app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    tg_app.add_handler(CommandHandler("refresh",   cmd_refresh))
    tg_app.add_handler(CommandHandler("summary",   cmd_summary))
    tg_app.add_handler(MessageHandler(filters.Document.ALL, handle_excel))

    scheduler = AsyncIOScheduler(timezone=KST)
    scheduler.add_job(
        scheduled_send, "cron",
        day_of_week="mon-fri", hour=15, minute=35,
        kwargs={"label": "🇰🇷 KR 장 마감"},
    )
    scheduler.add_job(
        scheduled_send, "cron",
        day_of_week="tue-sat", hour=7, minute=0,
        kwargs={"label": "🇺🇸 US 장 마감"},
    )

    async def post_init(application):
        scheduler.start()

    tg_app.post_init = post_init

    log.info(f"\n  ✅ 봇 실행 중")
    log.info(f"  🌐 허브 URL: {public_url}")
    log.info(f"  📱 텔레그램에서 .xlsx 파일을 전송하세요\n")

    tg_app.run_polling()


if __name__ == "__main__":
    main()
