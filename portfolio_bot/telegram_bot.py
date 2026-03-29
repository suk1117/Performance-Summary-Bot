from __future__ import annotations
import asyncio
import logging

import pandas as pd
from telegram import Update
from telegram.error import BadRequest as TgBadRequest, Forbidden as TgForbidden
from telegram.ext import ContextTypes

import portfolio_bot.state as _state
from portfolio_bot.config import KST
from portfolio_bot.state import _build_lock, _building, _users_lock, all_users
from portfolio_bot.storage import get_user_token, load_cashflow, load_portfolios
from portfolio_bot.storage.history import load_history
from portfolio_bot.storage.cashflow import compute_combined_nav
from portfolio_bot.storage.history import save_snapshot
from portfolio_bot.flask_app import _get_user_state, build_dashboard_for

log = logging.getLogger(__name__)


# ────────────────────────────────────────
# 텍스트 요약
# ────────────────────────────────────────
def _summary_text(uid: int, pname: str) -> str:
    state = _get_user_state(uid)
    with _users_lock:
        p  = state["portfolios"][pname]
        df = p["df"].copy() if p.get("df") is not None else pd.DataFrame()
    for col in ["수익률(%)", "현재가", "등락률(%)", "USD_KRW"]:
        if col not in df.columns:
            df[col] = float("nan")
    ts    = p["last_update"].strftime("%m/%d %H:%M") if p.get("last_update") else "—"
    name  = p.get("name", "포트폴리오")
    token = get_user_token(uid)
    url   = f"{_state.public_url}/u/{uid}/p/{pname}?t={token}"

    lines = [f"📊 *{name} 요약* `{ts} KST`\n"]
    usd_krw_s = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns and len(df) > 0 else 1370.0
    cashflows_s  = load_cashflow(uid, pname)
    net_inv_s    = sum(c["amount"] for c in cashflows_s if c["type"] == "in") \
                 - sum(c["amount"] for c in cashflows_s if c["type"] == "out")
    row_data     = []
    total_buy_s  = 0.0
    stock_eval_s = 0.0
    for _, r in df.iterrows():
        fx  = usd_krw_s if str(r.get("통화", "KRW")).upper() == "USD" else 1.0
        qty = float(r["수량"]) if pd.notna(r.get("수량")) else 0.0
        total_buy_s  += float(r["평단가"]) * qty * fx
        cur = float(r["현재가"]) if pd.notna(r.get("현재가")) else float(r["평단가"])
        stock_eval_s += cur * qty * fx
        row_data.append(r)
    cash_s       = max(0.0, net_inv_s - total_buy_s) if net_inv_s > 0 else 0.0
    total_ev_s   = stock_eval_s + cash_s
    _w_scale_s   = stock_eval_s / total_ev_s if total_ev_s > 0 else 1.0
    valid = df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
    if not valid.empty:
        buy_w = valid.apply(
            lambda r: float(r["평단가"]) * (float(r["수량"]) if pd.notna(r.get("수량")) else 0.0)
                      * (usd_krw_s if str(r.get("통화", "KRW")).upper() == "USD" else 1.0), axis=1
        )
        total = (valid["수익률(%)"] * buy_w).sum() / buy_w.sum() if buy_w.sum() > 0 else 0.0
        emoji = "🟢" if total >= 0 else "🔴"
        lines.append(f"{emoji} *종목 수익률: {'+' if total>=0 else ''}{total:.2f}%*\n")

    history_s = load_history(uid, pname)
    if history_s:
        last_d = sorted(history_s.keys())[-1]
        nav_ret = history_s[last_d].get("nav_return")
        if nav_ret is not None:
            nav_emoji = "🟢" if nav_ret >= 0 else "🔴"
            lines.append(f"{nav_emoji} *계좌 수익률(NAV): {'+' if nav_ret>=0 else ''}{nav_ret:.2f}%*\n")

    all_pnames = list(state["portfolios"].keys())
    if len(all_pnames) > 1:
        c_total = 0.0
        for _pn, _p in state["portfolios"].items():
            _df = _p.get("df")
            if _df is None or len(_df) == 0:
                continue
            _usd = float(_df["USD_KRW"].iloc[0]) if "USD_KRW" in _df.columns and len(_df) > 0 else 1370.0
            _s_eval = 0.0
            _t_buy  = 0.0
            for _, _r in _df.iterrows():
                _m   = _usd if str(_r.get("통화", "KRW")).upper() == "USD" else 1.0
                _q   = float(_r["수량"]) if pd.notna(_r.get("수량")) else 0.0
                _cur = float(_r["현재가"]) if pd.notna(_r.get("현재가")) else float(_r["평단가"])
                _s_eval += _cur * _q * _m
                _t_buy  += float(_r["평단가"]) * _q * _m
            _cf   = load_cashflow(uid, _pn)
            _ni   = (sum(c["amount"] for c in _cf if c["type"] == "in")
                   - sum(c["amount"] for c in _cf if c["type"] == "out"))
            _cash = max(0.0, _ni - _t_buy) if _ni > 0 else 0.0
            c_total += _s_eval + _cash
        c_nav, _ = compute_combined_nav(uid, all_pnames, c_total)
        c_nav_ret = (c_nav / 1000.0 - 1) * 100
        c_emoji   = "🟢" if c_nav_ret >= 0 else "🔴"
        lines.append(f"{c_emoji} *전체 계좌 수익률: {'+' if c_nav_ret>=0 else ''}{c_nav_ret:.2f}%*\n")

    lines.append("```")
    lines.append(f"{'종목':<10} {'비중':>5} {'수익률':>8}")
    lines.append("─" * 26)
    for r in row_data:
        ret     = r["수익률(%)"]
        ret_str = "   —  " if pd.isna(ret) else f"{'+' if ret>=0 else ''}{ret:.2f}%"
        lines.append(f"{r['종목명']:<10} {r['비중(%)'] * _w_scale_s:>4.1f}% {ret_str:>8}")
    lines.append("```")
    lines.append(f"\n🔗 [대시보드]({url})")
    return "\n".join(lines)


# ────────────────────────────────────────
# 커맨드 핸들러
# ────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *사용법*\n\n"
        "명령어\n"
        "  `/portfolio` — 전체 포트폴리오 목록 + URL\n"
        "  `/run`       — 활성 포트폴리오 URL\n"
        "  `/refresh`   — 가격 재조회\n"
        "  `/summary`   — 텍스트 요약\n\n"
        "자동 알림\n"
        "  🇰🇷 KST 15:35 / 🇺🇸 KST 07:00",
        parse_mode=None,
    )


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    state = _get_user_state(uid)
    token = get_user_token(uid)
    active = state["active_pname"]
    url = f"{_state.public_url}/u/{uid}/p/{active}?t={token}" if active else _state.public_url
    await update.message.reply_text(
        f"📊 *대시보드 URL*\n\n🔗 {url}",
        parse_mode=None,
        disable_web_page_preview=True,
    )


async def cmd_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid          = update.effective_user.id
    state        = _get_user_state(uid)
    portfolios   = state["portfolios"]
    active_pname = state["active_pname"]
    token        = get_user_token(uid)
    if not portfolios:
        await update.message.reply_text("⚠️ 포트폴리오가 없습니다.")
        return
    lines = ["📁 *포트폴리오 목록*\n"]
    for pname, p in portfolios.items():
        name = p.get("name", pname)
        ts   = p["last_update"].strftime("%m/%d %H:%M") if p.get("last_update") else "—"
        mark = "▶ " if pname == active_pname else "   "
        url  = f"{_state.public_url}/u/{uid}/p/{pname}?t={token}"
        lines.append(f"{mark}*{name}* `{ts}`\n🔗 {url}")
    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode=None,
        disable_web_page_preview=True,
    )


async def cmd_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid          = update.effective_user.id
    state        = _get_user_state(uid)
    active_pname = state["active_pname"]
    if active_pname not in state["portfolios"]:
        await update.message.reply_text("⚠️ 포트폴리오가 없습니다.")
        return
    _df = state["portfolios"][active_pname].get("df")
    if _df is None or len(_df) == 0:
        await update.message.reply_text("⚠️ 종목을 먼저 추가해 주세요.")
        return
    msg = await update.message.reply_text("🔄 가격 재조회 중...")
    try:
        await asyncio.get_running_loop().run_in_executor(None, build_dashboard_for, uid, active_pname)
        ts    = state["portfolios"][active_pname]["last_update"].strftime("%m/%d %H:%M")
        token = get_user_token(uid)
        url   = f"{_state.public_url}/u/{uid}/p/{active_pname}?t={token}"
        await msg.edit_text(
            f"✅ *업데이트 완료*\n\n🕐 `{ts} KST`\n🔗 {url}",
            parse_mode=None,
        )
    except Exception as e:
        await msg.edit_text(f"❌ 오류: {e}")


async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid          = update.effective_user.id
    state        = _get_user_state(uid)
    active_pname = state["active_pname"]
    if active_pname not in state["portfolios"]:
        await update.message.reply_text("⚠️ 포트폴리오가 없습니다.")
        return
    await update.message.reply_text(
        _summary_text(uid, active_pname),
        parse_mode=None,
        disable_web_page_preview=True,
    )


# ────────────────────────────────────────
# 자동 스케줄
# ────────────────────────────────────────
async def scheduled_send(label: str):
    if not all_users:
        log.info(f"⏰ {label} — 유저 없음, 건너뜀")
        return
    log.info(f"⏰ 자동 전송 시작 ({label})")
    for uid, state in list(all_users.items()):
        for pname in list(state["portfolios"].keys()):
            p = state["portfolios"][pname]
            if p.get("df") is None or len(p.get("df", [])) == 0:
                continue
            try:
                key = (uid, pname)
                already_building = False
                with _build_lock:
                    already_building = key in _building

                if already_building:
                    # 빌드 중이면 최대 30초 대기
                    for _ in range(30):
                        await asyncio.sleep(1)
                        with _build_lock:
                            if key not in _building:
                                break
                else:
                    await asyncio.get_running_loop().run_in_executor(
                        None, build_dashboard_for, uid, pname
                    )
                if pname not in state["portfolios"]:
                    continue
                text = f"⏰ *{label} 자동 업데이트*\n\n{_summary_text(uid, pname)}"
                await _state.tg_bot.send_message(
                    chat_id=uid,
                    text=text,
                    parse_mode=None,
                    disable_web_page_preview=True,
                )
                log.info(f"  → uid={uid} {p.get('name')} ({pname}) 전송 완료")
            except TgForbidden as e:
                log.warning(f"  → uid={uid} {pname} 봇 차단/미시작: {e}")
            except TgBadRequest as e:
                log.warning(f"  → uid={uid} {pname} 봇 차단/미시작: {e}")
            except Exception as e:
                log.error(f"  → uid={uid} {pname} 전송 실패: {e}")


async def scheduled_snapshot():
    """가격 재조회 없이 현재 df 기준으로 모든 유저·포트폴리오 스냅샷 저장."""
    for uid, state in list(all_users.items()):
        for pname, p in list(state["portfolios"].items()):
            with _users_lock:
                _df = p.get("df")
                df  = _df.copy() if _df is not None and len(_df) > 0 else None
            if df is None or len(df) == 0:
                continue
            try:
                usd_krw = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns else 1370.0
                save_snapshot(uid, pname, df, usd_krw)
                log.info(f"  📸 자정 스냅샷: uid={uid} {p.get('name', pname)}")
            except Exception as e:
                log.error(f"  ⚠️  자정 스냅샷 실패 uid={uid} {pname}: {e}")
