from __future__ import annotations
import logging
import os
import sys
import threading

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import portfolio_bot.state as _state
from portfolio_bot.config import (
    DATA_DIR, FLASK_PORT, FLASK_PUBLIC_URL, KST, TELEGRAM_CHAT_ID,
    TELEGRAM_TOKEN, USE_NGROK,
)
from portfolio_bot.flask_app import _get_user_state, run_flask, start_ngrok
from portfolio_bot.telegram_bot import (
    cmd_help, cmd_portfolio, cmd_refresh, cmd_run, cmd_summary,
    scheduled_send, scheduled_snapshot,
)

log = logging.getLogger(__name__)


def main():
    # ── 중복 실행 방지 (파일 잠금) ──
    _lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".bot.lock")
    try:
        if sys.platform == "win32":
            import msvcrt as _msvcrt
            _lock_fd = open(_lock_path, "wb")
            _msvcrt.locking(_lock_fd.fileno(), _msvcrt.LK_NBLCK, 1)
        else:
            import fcntl as _fcntl
            _lock_fd = open(_lock_path, "wb")
            _fcntl.flock(_lock_fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
    except OSError:
        log.error(
            "❌ 봇이 이미 실행 중입니다. "
            "기존 프로세스를 종료한 후 다시 실행하세요."
        )
        sys.exit(1)

    log.info("=" * 55)
    log.info("  📊  포트폴리오 봇 시작 (멀티유저)")
    log.info("=" * 55)

    # 디스크에 저장된 모든 유저 로드
    _loaded = 0
    if os.path.isdir(DATA_DIR):
        for _entry in os.scandir(DATA_DIR):
            if _entry.is_dir() and _entry.name.startswith("user_"):
                try:
                    _uid = int(_entry.name.split("_", 1)[1])
                    _get_user_state(_uid)
                    _loaded += 1
                except (ValueError, Exception):
                    pass
    # TELEGRAM_CHAT_ID가 위에서 로드 안 됐으면 추가 로드
    if TELEGRAM_CHAT_ID and TELEGRAM_CHAT_ID not in _state.all_users:
        _get_user_state(TELEGRAM_CHAT_ID)
        _loaded += 1
    log.info(f"  📁 전체 유저 {_loaded}명 포트폴리오 로드 완료")

    threading.Thread(target=run_flask, daemon=True).start()
    log.info(f"  🖥️  Flask 서버 시작 (port {FLASK_PORT})")

    if USE_NGROK:
        start_ngrok()
    elif FLASK_PUBLIC_URL:
        _state.public_url = FLASK_PUBLIC_URL.rstrip("/")
        log.info(f"  🌐 공인 IP 모드: {_state.public_url}")
    else:
        log.warning("  ⚠️  USE_NGROK=false이지만 FLASK_PUBLIC_URL 미설정 — 대시보드 링크가 비어 있습니다")

    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    _state.tg_bot = tg_app.bot
    tg_app.add_handler(CommandHandler("start",     cmd_help))
    tg_app.add_handler(CommandHandler("help",      cmd_help))
    tg_app.add_handler(CommandHandler("run",       cmd_run))
    tg_app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    tg_app.add_handler(CommandHandler("refresh",   cmd_refresh))
    tg_app.add_handler(CommandHandler("summary",   cmd_summary))

    async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        from telegram.error import Conflict, NetworkError
        err = context.error
        if isinstance(err, Conflict):
            log.warning("⚠️  Telegram Conflict: 다른 봇 인스턴스가 실행 중입니다. 기존 프로세스를 종료하세요.")
            return
        if isinstance(err, NetworkError):
            log.debug(f"네트워크 오류 (재시도 예정): {err}")
            return
        log.error(f"봇 오류: {err}", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(f"❌ 오류가 발생했습니다: {err}")
            except Exception:
                pass

    tg_app.add_error_handler(_error_handler)

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
    scheduler.add_job(
        scheduled_snapshot, "cron",
        hour=0, minute=1,
    )

    async def post_init(application):
        scheduler.start()

    tg_app.post_init = post_init

    log.info(f"\n  ✅ 봇 실행 중")
    log.info(f"  🌐 URL: {_state.public_url}")
    log.info(f"  📱 텔레그램 봇 준비 완료\n")

    tg_app.run_polling()


if __name__ == "__main__":
    main()
