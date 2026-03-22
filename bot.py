"""
bot.py  ─  포트폴리오 대시보드 텔레그램 봇 (멀티 포트폴리오)
────────────────────────────────────────────────────
명령어
  /portfolio  포트폴리오 목록 + URL
  /refresh    활성 포트폴리오 가격 재조회
  /summary    활성 포트폴리오 텍스트 요약
  /run        대시보드 URL
  /help       사용법

자동 스케줄 (KST)
  15:35  KR 장 마감
  07:00  US 장 마감
────────────────────────────────────────────────────
"""

import os
import sys
import asyncio
import threading
import logging
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import pytz
from flask import Flask, abort, jsonify, redirect, request
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

from price_fetcher import fetch_prices
from html_builder import build_user_html
from storage import (
    load_portfolios, save_portfolios,
    create_portfolio, rename_portfolio, delete_portfolio,
    save_snapshot, load_cashflow, add_cashflow,
)

# ══════════════════════════════════════════
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "여기에_텔레그램_토큰_입력")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
NGROK_TOKEN      = os.getenv("NGROK_TOKEN",       "여기에_ngrok_토큰_입력")
FLASK_PORT       = 5050
KST              = pytz.timezone("Asia/Seoul")
# ══════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S", level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── 전역 상태 ──
# portfolios[pname] = { "name", "last_update", "df" }
portfolios:   dict = {}
active_pname: str  = ""
public_url:   str  = ""

# ── 대시보드 빌드 중복 방지 ──
_build_lock  = threading.Lock()   # _building / _hist_check 접근용
_building:   set  = set()         # 현재 빌드 중인 pname
_hist_check: dict = {}            # pname -> "YYYY-MM-DD" (오늘 이미 완료)

app_flask    = Flask(__name__)
REQUIRED_COLS = {"종목명", "국가", "평단가", "수량", "통화"}


def _is_owner(update: Update) -> bool:
    return update.effective_user.id == TELEGRAM_CHAT_ID


@app_flask.after_request
def skip_ngrok_warning(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response


# ────────────────────────────────────────
# Flask 라우트
# ────────────────────────────────────────
@app_flask.route("/")
def index():
    if active_pname and active_pname in portfolios:
        return redirect(f"/p/{active_pname}")
    if portfolios:
        return redirect(f"/p/{next(iter(portfolios))}")
    return "<p>포트폴리오 없음</p>", 404


@app_flask.route("/p/<pname>")
def portfolio_page(pname: str):
    global active_pname
    if pname not in portfolios:
        abort(404)
    active_pname = pname
    save_portfolios(portfolios, active_pname)
    p = portfolios[pname]
    if p.get("df") is not None and len(p["df"]) > 0:
        _trigger_build_if_needed(pname)
    return build_user_html(
        p["df"],
        display_name=p.get("name", "포트폴리오"),
        cashflows=load_cashflow(pname),
        pname=pname,
        all_portfolios=portfolios,
    )


# ── 포트폴리오 관리 ──
@app_flask.route("/api/portfolios", methods=["POST"])
def api_create_portfolio():
    data = request.get_json()
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "이름을 입력하세요"}), 400
    pname = create_portfolio(name)
    portfolios[pname] = {
        "name":        name,
        "last_update": None,
        "df":          pd.DataFrame(columns=["종목명", "국가", "비중(%)", "평단가", "수량", "통화"]),
    }
    return jsonify({"ok": True, "pname": pname})


@app_flask.route("/api/portfolios/<pname>", methods=["PATCH"])
def api_rename_portfolio(pname: str):
    if pname not in portfolios:
        return jsonify({"error": "포트폴리오 없음"}), 404
    data = request.get_json()
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "이름을 입력하세요"}), 400
    portfolios[pname]["name"] = name
    rename_portfolio(pname, name)
    return jsonify({"ok": True})


@app_flask.route("/api/portfolios/<pname>", methods=["DELETE"])
def api_delete_portfolio(pname: str):
    global active_pname
    if pname not in portfolios:
        return jsonify({"error": "포트폴리오 없음"}), 404
    if len(portfolios) <= 1:
        return jsonify({"error": "마지막 포트폴리오는 삭제할 수 없습니다"}), 400
    del portfolios[pname]
    new_active = delete_portfolio(pname)
    if not new_active or new_active not in portfolios:
        new_active = next(iter(portfolios))
    active_pname = new_active
    return jsonify({"ok": True, "redirect": f"/p/{new_active}"})


# ── 종목 추가/수정 ──
@app_flask.route("/api/p/<pname>/stock", methods=["POST"])
def api_add_stock(pname: str):
    if pname not in portfolios:
        portfolios[pname] = {
            "name": pname, "last_update": None,
            "df": pd.DataFrame(columns=["종목명", "국가", "비중(%)", "평단가", "수량", "통화"]),
        }
    data = request.get_json()
    try:
        name     = str(data["종목명"]).strip()
        country  = str(data["국가"]).strip()
        qty      = float(data["수량"])
        avg      = float(data["평단가"])
        currency = "USD" if country == "US" else "KRW"

        df = portfolios[pname]["df"].copy()
        if "비중(%)" not in df.columns:
            df["비중(%)"] = 0.0
        if name in df["종목명"].values:
            df.loc[df["종목명"] == name, ["국가", "평단가", "수량", "통화"]] = \
                [country, avg, qty, currency]
        else:
            new_row = pd.DataFrame([{
                "종목명": name, "국가": country,
                "비중(%)": 0.0, "평단가": avg, "수량": qty, "통화": currency,
            }])
            df = pd.concat([df, new_row], ignore_index=True)

        drop_cols = [c for c in ["현재가", "수익률(%)", "등락률(%)", "USD_KRW"] if c in df.columns]
        portfolios[pname]["df"] = df.drop(columns=drop_cols)
        save_portfolios(portfolios, active_pname)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── 종목 삭제 ──
@app_flask.route("/api/p/<pname>/stock/<path:name>", methods=["DELETE"])
def api_del_stock(pname: str, name: str):
    if pname not in portfolios:
        return jsonify({"error": "포트폴리오 없음"}), 404
    df = portfolios[pname]["df"]
    if name not in df["종목명"].values:
        return jsonify({"error": "종목 없음"}), 404
    portfolios[pname]["df"] = df[df["종목명"] != name].reset_index(drop=True)
    save_portfolios(portfolios, active_pname)
    return jsonify({"ok": True})


# ── 가격 재조회 ──
@app_flask.route("/api/p/<pname>/refresh", methods=["POST"])
def api_refresh(pname: str):
    if pname not in portfolios:
        return jsonify({"error": "포트폴리오 없음"}), 404
    df = portfolios[pname].get("df")
    if df is None or len(df) == 0:
        return jsonify({"error": "종목을 먼저 추가해 주세요"}), 400
    try:
        build_dashboard_for(pname)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 자금 기록 ──
@app_flask.route("/api/cashflow/<pname>", methods=["GET"])
def api_get_cashflow(pname: str):
    return jsonify(load_cashflow(pname))


@app_flask.route("/api/cashflow/<pname>", methods=["POST"])
def api_add_cashflow_route(pname: str):
    data = request.get_json()
    try:
        type_  = str(data["type"]).strip()
        amount = float(data["amount"])
        memo   = str(data.get("memo", "")).strip()
        if type_ not in ("in", "out"):
            return jsonify({"error": "type은 'in' 또는 'out'이어야 합니다"}), 400
        if amount <= 0:
            return jsonify({"error": "금액은 0보다 커야 합니다"}), 400
        add_cashflow(pname, type_, amount, memo)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


def run_flask():
    app_flask.run(port=FLASK_PORT, use_reloader=False)


# ────────────────────────────────────────
# ngrok
# ────────────────────────────────────────
def _find_existing_tunnel() -> str:
    import urllib.request, json as _json
    for port in range(4040, 4045):
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/api/tunnels", timeout=2) as r:
                tunnels = _json.loads(r.read())["tunnels"]
            for t in tunnels:
                addr = t.get("config", {}).get("addr", "")
                if str(FLASK_PORT) in addr:
                    return t["public_url"].replace("http://", "https://")
        except Exception:
            pass
    return ""


def start_ngrok() -> str:
    import time
    from pyngrok import ngrok, conf as ngrok_conf
    from pyngrok.exception import PyngrokNgrokHTTPError, PyngrokNgrokError
    global public_url

    existing = _find_existing_tunnel()
    if existing:
        public_url = existing
        log.info(f"🌐 기존 ngrok 터널 재사용: {public_url}")
        return public_url

    ngrok_conf.get_default().auth_token = NGROK_TOKEN
    for attempt in range(10):
        try:
            tunnel    = ngrok.connect(FLASK_PORT, "http")
            public_url = tunnel.public_url.replace("http://", "https://")
            log.info(f"🌐 ngrok URL: {public_url}")
            return public_url
        except (PyngrokNgrokHTTPError, PyngrokNgrokError) as e:
            if ("already online" in str(e) or "ERR_NGROK_108" in str(e)) and attempt < 9:
                log.info(f"ngrok 세션 해제 대기 중... (20초, {attempt+1}/10)")
                time.sleep(20)
            else:
                raise
    return public_url


# ────────────────────────────────────────
# 가격 조회
# ────────────────────────────────────────
def build_dashboard_for(pname: str) -> pd.DataFrame:
    p      = portfolios[pname]
    df_raw = p["df"].drop(
        columns=[c for c in ["현재가", "수익률(%)", "등락률(%)", "USD_KRW"] if c in p["df"].columns]
    )
    df = fetch_prices(df_raw)
    portfolios[pname]["df"]          = df
    portfolios[pname]["last_update"] = datetime.now(KST)
    usd_krw = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns and len(df) > 0 else 1370.0
    save_snapshot(pname, df, usd_krw)
    save_portfolios(portfolios, active_pname)
    return df


def _build_dashboard_bg(pname: str) -> None:
    """백그라운드 스레드용 wrapper — 완료 후 _building에서 제거."""
    try:
        build_dashboard_for(pname)
    finally:
        with _build_lock:
            _building.discard(pname)


def _trigger_build_if_needed(pname: str) -> None:
    """오늘 아직 빌드하지 않았고, 현재 빌드 중이 아닐 때만 스레드 1개 생성."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    with _build_lock:
        if _hist_check.get(pname) == today or pname in _building:
            return
        _building.add(pname)
        _hist_check[pname] = today  # 스레드 시작 전에 기록 (중복 방지)
    threading.Thread(target=_build_dashboard_bg, args=(pname,), daemon=True).start()


# ────────────────────────────────────────
# 텍스트 요약
# ────────────────────────────────────────
def _summary_text(pname: str) -> str:
    p    = portfolios[pname]
    df   = p["df"]
    ts   = p["last_update"].strftime("%m/%d %H:%M") if p.get("last_update") else "—"
    name = p.get("name", "포트폴리오")
    url  = f"{public_url}/p/{pname}"

    lines = [f"📊 *{name} 요약* `{ts} KST`\n"]
    valid = df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
    if not valid.empty:
        total = (valid["비중(%)"] * valid["수익률(%)"]).sum() / valid["비중(%)"].sum()
        emoji = "🟢" if total >= 0 else "🔴"
        lines.append(f"{emoji} *가중 평균 수익률: {'+' if total>=0 else ''}{total:.2f}%*\n")

    lines.append("```")
    lines.append(f"{'종목':<10} {'비중':>5} {'수익률':>8}")
    lines.append("─" * 26)
    for _, r in df.iterrows():
        ret     = r["수익률(%)"]
        ret_str = "   —  " if pd.isna(ret) else f"{'+' if ret>=0 else ''}{ret:.2f}%"
        lines.append(f"{r['종목명']:<10} {r['비중(%)']:>4.1f}% {ret_str:>8}")
    lines.append("```")
    lines.append(f"\n🔗 [대시보드]({url})")
    return "\n".join(lines)


# ────────────────────────────────────────
# 커맨드 핸들러
# ────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    await update.message.reply_text(
        "📋 *사용법*\n\n"
        "명령어\n"
        "  `/portfolio` — 전체 포트폴리오 목록 + URL\n"
        "  `/run`       — 활성 포트폴리오 URL\n"
        "  `/refresh`   — 가격 재조회\n"
        "  `/summary`   — 텍스트 요약\n\n"
        "자동 알림\n"
        "  🇰🇷 KST 15:35 / 🇺🇸 KST 07:00",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    url = f"{public_url}/p/{active_pname}" if active_pname else public_url
    await update.message.reply_text(
        f"📊 *대시보드 URL*\n\n🔗 {url}",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def cmd_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    if not portfolios:
        await update.message.reply_text("⚠️ 포트폴리오가 없습니다.")
        return
    lines = ["📁 *포트폴리오 목록*\n"]
    for pname, p in portfolios.items():
        name = p.get("name", pname)
        ts   = p["last_update"].strftime("%m/%d %H:%M") if p.get("last_update") else "—"
        mark = "▶ " if pname == active_pname else "   "
        url  = f"{public_url}/p/{pname}"
        lines.append(f"{mark}*{name}* `{ts}`\n🔗 {url}")
    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def cmd_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    if active_pname not in portfolios:
        await update.message.reply_text("⚠️ 포트폴리오가 없습니다.")
        return
    msg = await update.message.reply_text("🔄 가격 재조회 중...")
    try:
        await asyncio.get_running_loop().run_in_executor(None, build_dashboard_for, active_pname)
        ts  = portfolios[active_pname]["last_update"].strftime("%m/%d %H:%M")
        url = f"{public_url}/p/{active_pname}"
        await msg.edit_text(
            f"✅ *업데이트 완료*\n\n🕐 `{ts} KST`\n🔗 {url}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await msg.edit_text(f"❌ 오류: {e}")


async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    if active_pname not in portfolios:
        await update.message.reply_text("⚠️ 포트폴리오가 없습니다.")
        return
    await update.message.reply_text(
        _summary_text(active_pname),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


# ────────────────────────────────────────
# 자동 스케줄
# ────────────────────────────────────────
async def scheduled_send(label: str):
    if not portfolios:
        log.info(f"⏰ {label} — 포트폴리오 없음, 건너뜀")
        return
    log.info(f"⏰ 자동 전송 시작 ({label})")
    bot = Bot(token=TELEGRAM_TOKEN)
    for pname in list(portfolios.keys()):
        p = portfolios[pname]
        if p.get("df") is None or len(p.get("df", [])) == 0:
            continue
        try:
            await asyncio.get_running_loop().run_in_executor(None, build_dashboard_for, pname)
            text = f"⏰ *{label} 자동 업데이트*\n\n{_summary_text(pname)}"
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            log.info(f"  → {p.get('name')} ({pname}) 전송 완료")
        except Exception as e:
            log.error(f"  → {pname} 전송 실패: {e}")


async def scheduled_snapshot():
    """가격 재조회 없이 현재 df 기준으로 모든 포트폴리오 스냅샷 저장"""
    if not portfolios:
        return
    for pname, p in list(portfolios.items()):
        df = p.get("df")
        if df is None or len(df) == 0:
            continue
        try:
            usd_krw = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns else 1370.0
            save_snapshot(pname, df, usd_krw)
            log.info(f"  📸 자정 스냅샷 저장: {p.get('name', pname)}")
        except Exception as e:
            log.error(f"  ⚠️  자정 스냅샷 실패 ({pname}): {e}")


# ────────────────────────────────────────
# MAIN
# ────────────────────────────────────────
def main():
    global portfolios, active_pname

    log.info("=" * 55)
    log.info("  📊  포트폴리오 봇 시작 (멀티 포트폴리오)")
    log.info("=" * 55)

    portfolios, active_pname = load_portfolios()
    log.info(f"  📁 포트폴리오 {len(portfolios)}개 로드, 활성: {active_pname}")

    threading.Thread(target=run_flask, daemon=True).start()
    log.info(f"  🖥️  Flask 서버 시작 (port {FLASK_PORT})")

    start_ngrok()

    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(CommandHandler("start",     cmd_help))
    tg_app.add_handler(CommandHandler("help",      cmd_help))
    tg_app.add_handler(CommandHandler("run",       cmd_run))
    tg_app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    tg_app.add_handler(CommandHandler("refresh",   cmd_refresh))
    tg_app.add_handler(CommandHandler("summary",   cmd_summary))
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
    log.info(f"  🌐 URL: {public_url}")
    log.info(f"  📱 텔레그램 봇 준비 완료\n")

    tg_app.run_polling()


if __name__ == "__main__":
    main()
