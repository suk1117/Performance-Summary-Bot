from __future__ import annotations
import json
import logging
import os
import secrets as _secrets
import tempfile
import threading

import pandas as pd
from flask import Flask, abort, jsonify, redirect, request

from portfolio_bot.config import DATA_DIR, FLASK_PORT, FLASK_PUBLIC_URL, KST, NGROK_TOKEN, \
    TELEGRAM_CHAT_ID, USE_NGROK
from portfolio_bot.state import (
    _build_lock, _building, _hist_check,
    _users_lock, all_users, public_url as _pub_url,
)
from portfolio_bot.storage import (
    add_cashflow, create_portfolio, delete_portfolio, get_user_token,
    load_cashflow, load_portfolios, load_trades, save_portfolios,
)
from portfolio_bot.storage.trades import _trades_path
from portfolio_bot.html_builder import build_combined_html, build_user_html
from portfolio_bot.price_fetcher import fetch_prices
from portfolio_bot.storage.history import save_snapshot

import portfolio_bot.state as _state

log = logging.getLogger(__name__)

app_flask    = Flask(__name__)
REQUIRED_COLS = {"종목명", "국가", "평단가", "수량", "통화"}


@app_flask.errorhandler(400)
@app_flask.errorhandler(403)
@app_flask.errorhandler(404)
@app_flask.errorhandler(500)
def _json_error(e):
    if getattr(e, "code", 500) == 500:
        import traceback as _tb
        log.error("Flask 500 오류:\n" + _tb.format_exc())
    return jsonify({"error": str(e)}), e.code


def _get_user_state(uid: int) -> dict:
    """uid의 상태 반환. 없으면 디스크에서 로드."""
    if uid not in all_users:
        # 락 밖에서 미리 로드 — 중복 로드 가능하지만 결과 동일하므로 안전
        portfolios, active_pname = load_portfolios(uid)
        with _users_lock:
            # double-check: 다른 스레드가 먼저 로드했을 수 있음
            if uid not in all_users:
                all_users[uid] = {"portfolios": portfolios, "active_pname": active_pname}
    return all_users[uid]


def _check_token(uid: int):
    """URL 토큰 검증. 불일치 또는 빈 토큰이면 403."""
    token = request.args.get("t", "")
    if not token:
        abort(403)
    if not _secrets.compare_digest(token, get_user_token(uid)):
        abort(403)


@app_flask.after_request
def skip_ngrok_warning(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response


# ────────────────────────────────────────
# Flask 라우트
# ────────────────────────────────────────
@app_flask.route("/")
def index():
    """레거시 진입점 — TELEGRAM_CHAT_ID 기준으로 리다이렉트."""
    uid   = TELEGRAM_CHAT_ID
    token = get_user_token(uid)
    state = _get_user_state(uid)
    pname = state["active_pname"]
    if pname and pname in state["portfolios"]:
        return redirect(f"/u/{uid}/p/{pname}?t={token}")
    if state["portfolios"]:
        return redirect(f"/u/{uid}/p/{next(iter(state['portfolios']))}?t={token}")
    return "<p>포트폴리오 없음</p>", 404


@app_flask.route("/p/<pname>")
def legacy_portfolio_page(pname: str):
    """레거시 URL → 새 URL 리다이렉트."""
    uid   = TELEGRAM_CHAT_ID
    token = get_user_token(uid)
    return redirect(f"/u/{uid}/p/{pname}?t={token}")


@app_flask.route("/u/<int:uid>")
def index_user(uid: int):
    _check_token(uid)
    state = _get_user_state(uid)
    token = get_user_token(uid)
    pname = state["active_pname"]
    if pname and pname in state["portfolios"]:
        return redirect(f"/u/{uid}/p/{pname}?t={token}")
    if state["portfolios"]:
        return redirect(f"/u/{uid}/p/{next(iter(state['portfolios']))}?t={token}")
    return "<p>포트폴리오 없음</p>", 404


@app_flask.route("/u/<int:uid>/p/<pname>")
def portfolio_page(uid: int, pname: str):
    _check_token(uid)
    state = _get_user_state(uid)
    if pname not in state["portfolios"]:
        abort(404)
    with _users_lock:
        state["active_pname"] = pname
        save_portfolios(uid, state["portfolios"], pname)
        p = state["portfolios"][pname]
    token = get_user_token(uid)
    if p.get("df") is not None and len(p["df"]) > 0:
        _trigger_build_if_needed(uid, pname)
    return build_user_html(
        p["df"],
        display_name=p.get("name", "포트폴리오"),
        cashflows=load_cashflow(uid, pname),
        pname=pname,
        all_portfolios=state["portfolios"],
        uid=uid,
        token=token,
        trades=load_trades(uid, pname),
    )


@app_flask.route("/u/<int:uid>/p/all")
def combined_page(uid: int):
    _check_token(uid)
    state = _get_user_state(uid)
    token = get_user_token(uid)
    if len(state["portfolios"]) < 2:
        pname = state["active_pname"] or next(iter(state["portfolios"]))
        return redirect(f"/u/{uid}/p/{pname}?t={token}")
    for pname, p in state["portfolios"].items():
        if p.get("df") is not None and len(p.get("df", [])) > 0:
            _trigger_build_if_needed(uid, pname)
    return build_combined_html(uid, token, state["portfolios"])


# ── 포트폴리오 관리 ──
@app_flask.route("/u/<int:uid>/api/portfolios", methods=["POST"])
def api_create_portfolio(uid: int):
    _check_token(uid)
    state = _get_user_state(uid)
    data  = request.get_json()
    name  = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "이름을 입력하세요"}), 400
    with _users_lock:
        pname = create_portfolio(uid, name)   # next_id 채번 (락 안에서 직렬화)
        state["portfolios"][pname] = {
            "name":        name,
            "last_update": None,
            "df":          pd.DataFrame(columns=["종목명", "국가", "비중(%)", "평단가", "수량", "통화"]),
        }
        save_portfolios(uid, state["portfolios"], state["active_pname"])
    return jsonify({"ok": True, "pname": pname})


@app_flask.route("/u/<int:uid>/api/portfolios/<pname>", methods=["PATCH"])
def api_rename_portfolio(uid: int, pname: str):
    _check_token(uid)
    state = _get_user_state(uid)
    if pname not in state["portfolios"]:
        return jsonify({"error": "포트폴리오 없음"}), 404
    data = request.get_json()
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "이름을 입력하세요"}), 400
    with _users_lock:
        state["portfolios"][pname]["name"] = name
        save_portfolios(uid, state["portfolios"], state["active_pname"])
    return jsonify({"ok": True})


@app_flask.route("/u/<int:uid>/api/portfolios/<pname>", methods=["DELETE"])
def api_delete_portfolio(uid: int, pname: str):
    _check_token(uid)
    state = _get_user_state(uid)
    portfolios = state["portfolios"]
    if pname not in portfolios:
        return jsonify({"error": "포트폴리오 없음"}), 404
    if len(portfolios) <= 1:
        return jsonify({"error": "마지막 포트폴리오는 삭제할 수 없습니다"}), 400
    with _users_lock:
        del portfolios[pname]
        delete_portfolio(uid, pname)          # 파일 삭제만
        if not portfolios:
            new_active = ""
        elif state["active_pname"] not in portfolios:
            new_active = next(iter(portfolios))
        else:
            new_active = state["active_pname"]
        state["active_pname"] = new_active
        save_portfolios(uid, portfolios, new_active)   # 인메모리로 디스크 저장
    with _build_lock:
        _building.discard((uid, pname))
        _hist_check.pop((uid, pname), None)
    token = get_user_token(uid)
    return jsonify({"ok": True, "redirect": f"/u/{uid}/p/{new_active}?t={token}"})


# ── 종목 추가/수정 ──
@app_flask.route("/u/<int:uid>/api/p/<pname>/stock", methods=["POST"])
def api_add_stock(uid: int, pname: str):
    from portfolio_bot.storage.trades import save_trade
    _check_token(uid)
    state = _get_user_state(uid)
    data = request.get_json()
    try:
        name     = str(data["종목명"]).strip()
        country  = str(data["국가"]).strip()
        qty      = float(data["수량"])
        avg      = float(data["평단가"])
        currency = "USD" if country == "US" else "KRW"

        with _users_lock:
            if pname not in state["portfolios"]:
                state["portfolios"][pname] = {
                    "name": pname, "last_update": None,
                    "df": pd.DataFrame(columns=["종목명", "국가", "비중(%)", "평단가", "수량", "통화"]),
                }
            df = state["portfolios"][pname]["df"].copy()
            if "비중(%)" not in df.columns:
                df["비중(%)"] = 0.0
            if name in df["종목명"].values:
                old_qty = float(df.loc[df["종목명"] == name, "수량"].values[0])
                old_avg = float(df.loc[df["종목명"] == name, "평단가"].values[0])
                if name != "현금":
                    diff = qty - old_qty
                    if diff > 0:
                        # avg = 사용자가 입력한 추가 매수 단가
                        # new_avg = 가중평균 (df에 저장할 올바른 평단가)
                        new_avg = (old_qty * old_avg + diff * avg) / qty
                        df.loc[df["종목명"] == name, ["국가", "평단가", "수량", "통화"]] = \
                            [country, round(new_avg, 2), qty, currency]
                        # price=avg(추가매수단가), display_avg도 avg로 통일 (단가×수량=금액 일관성)
                        save_trade(uid, pname, "추가매수", name, diff, round(avg, 2))
                    elif diff < 0:
                        if qty == 0:
                            # 수량을 0으로 입력 → 전량 매도 처리 후 종목 삭제
                            # avg = 사용자가 입력한 매도 단가
                            df = df[df["종목명"] != name].reset_index(drop=True)
                            save_trade(uid, pname, "전량매도", name, old_qty,
                                       round(avg, 2), display_avg=round(old_avg, 2))
                        else:
                            # avg = 사용자가 입력한 매도 단가
                            # df에는 old_avg 유지 (매도해도 매수 평단가 변동 없음)
                            df.loc[df["종목명"] == name, ["국가", "평단가", "수량", "통화"]] = \
                                [country, old_avg, qty, currency]
                            # price=avg(매도단가), display_avg=old_avg(매수평단가) → realized_pnl 자동 계산
                            save_trade(uid, pname, "일부매도", name, abs(diff),
                                       round(avg, 2), display_avg=round(old_avg, 2))
                    else:
                        # 수량 동일 (평단가·국가만 수정): 그대로 저장
                        df.loc[df["종목명"] == name, ["국가", "평단가", "수량", "통화"]] = \
                            [country, avg, qty, currency]
                else:
                    # 현금: 기존처럼 그대로 저장
                    df.loc[df["종목명"] == name, ["국가", "평단가", "수량", "통화"]] = \
                        [country, avg, qty, currency]
            else:
                new_row = pd.DataFrame([{
                    "종목명": name, "국가": country,
                    "비중(%)": 0.0, "평단가": avg, "수량": qty, "통화": currency,
                }])
                df = pd.concat([df, new_row], ignore_index=True)
                if name != "현금" and qty > 0:
                    save_trade(uid, pname, "신규매수", name, qty, avg)
            drop_cols = [c for c in ["현재가", "수익률(%)", "등락률(%)", "USD_KRW"] if c in df.columns]
            state["portfolios"][pname]["df"] = df.drop(columns=drop_cols)
            save_portfolios(uid, state["portfolios"], state["active_pname"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── 종목 삭제 ──
@app_flask.route("/u/<int:uid>/api/p/<pname>/stock/<path:name>", methods=["DELETE"])
def api_del_stock(uid: int, pname: str, name: str):
    from portfolio_bot.storage.trades import save_trade
    _check_token(uid)
    state = _get_user_state(uid)
    if pname not in state["portfolios"]:
        return jsonify({"error": "포트폴리오 없음"}), 404
    with _users_lock:
        df = state["portfolios"][pname]["df"].copy()
        if name not in df["종목명"].values:
            return jsonify({"error": "종목 없음"}), 404
        if name != "현금":
            _row = df[df["종목명"] == name].iloc[0]
            _del_qty = float(_row["수량"]) if pd.notna(_row.get("수량")) else 0.0
            _del_avg = float(_row["평단가"])
            if _del_qty > 0:
                save_trade(uid, pname, "전량매도", name, _del_qty, _del_avg, display_avg=None)
        state["portfolios"][pname]["df"] = df[df["종목명"] != name].reset_index(drop=True)
        save_portfolios(uid, state["portfolios"], state["active_pname"])
    return jsonify({"ok": True})


# ── 가격 재조회 ──
@app_flask.route("/u/<int:uid>/api/p/<pname>/refresh", methods=["POST"])
def api_refresh(uid: int, pname: str):
    from datetime import datetime
    _check_token(uid)
    state = _get_user_state(uid)
    if pname not in state["portfolios"]:
        return jsonify({"error": "포트폴리오 없음"}), 404
    df = state["portfolios"][pname].get("df")
    if df is None or len(df) == 0:
        return jsonify({"error": "종목을 먼저 추가해 주세요"}), 400
    key = (uid, pname)
    with _build_lock:
        already = key in _building
        if not already:
            _building.add(key)
            _hist_check[key] = datetime.now(KST).strftime("%Y-%m-%d")
    if not already:
        threading.Thread(target=_build_dashboard_bg, args=(uid, pname), daemon=True).start()
    return jsonify({"ok": True, "building": True})


# ── 지수 비교 ──
@app_flask.route("/u/<int:uid>/api/index_returns")
def api_index_returns(uid: int):
    _check_token(uid)
    import yfinance as yf
    start = request.args.get("start", "")
    if not start:
        return jsonify({})
    tickers = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "NASDAQ": "^IXIC", "S&P500": "^GSPC"}
    result = {}
    for name, ticker in tickers.items():
        try:
            df_idx = yf.download(ticker, start=start, progress=False, auto_adjust=True)
            if df_idx.empty:
                result[name] = []
                continue
            closes = df_idx["Close"]
            if isinstance(closes, pd.DataFrame):
                closes = closes.iloc[:, 0]
            elif hasattr(closes, "squeeze"):
                closes = closes.squeeze()
            closes = closes.dropna()
            if closes.empty:
                result[name] = []
                continue
            base = float(closes.iloc[0])
            if base == 0:
                result[name] = []
                continue
            result[name] = [
                {"date": str(d.date()), "return": round((float(v) - base) / base * 100, 4)}
                for d, v in closes.items()
            ]
        except Exception:
            result[name] = []
    return jsonify(result)


# ── 자금 기록 ──
@app_flask.route("/u/<int:uid>/api/cashflow/<pname>", methods=["GET"])
def api_get_cashflow(uid: int, pname: str):
    _check_token(uid)
    return jsonify(load_cashflow(uid, pname))


@app_flask.route("/u/<int:uid>/api/trades/<pname>", methods=["GET"])
def api_get_trades(uid: int, pname: str):
    _check_token(uid)
    return jsonify(load_trades(uid, pname))


@app_flask.route("/u/<int:uid>/api/trades/<pname>", methods=["DELETE"])
def api_clear_trades(uid: int, pname: str):
    _check_token(uid)
    fpath = _trades_path(uid, pname)
    if os.path.exists(fpath):
        os.remove(fpath)
    return jsonify({"ok": True})


@app_flask.route("/u/<int:uid>/api/trades/<pname>/<int:index>", methods=["DELETE"])
def api_delete_trade(uid: int, pname: str, index: int):
    _check_token(uid)
    records = load_trades(uid, pname)
    if index < 0 or index >= len(records):
        return jsonify({"error": "인덱스 범위 초과"}), 400
    records.pop(index)
    fpath   = _trades_path(uid, pname)
    dirpath = os.path.dirname(fpath)
    os.makedirs(dirpath, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                      dir=dirpath, delete=False, suffix=".tmp") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        tmp_path = f.name
    os.replace(tmp_path, fpath)
    return jsonify({"ok": True})


@app_flask.route("/u/<int:uid>/api/cashflow/<pname>", methods=["POST"])
def api_add_cashflow_route(uid: int, pname: str):
    _check_token(uid)
    state = _get_user_state(uid)
    if pname not in state["portfolios"]:
        return jsonify({"error": "포트폴리오 없음"}), 404
    data = request.get_json()
    try:
        type_  = str(data["type"]).strip()
        amount = float(data["amount"])
        memo   = str(data.get("memo", "")).strip()
        if type_ not in ("in", "out"):
            return jsonify({"error": "type은 'in' 또는 'out'이어야 합니다"}), 400
        if amount <= 0:
            return jsonify({"error": "금액은 0보다 커야 합니다"}), 400
        add_cashflow(uid, pname, type_, amount, memo)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


def run_flask():
    app_flask.run(host="0.0.0.0", port=FLASK_PORT, use_reloader=False)


# ────────────────────────────────────────
# 가격 조회
# ────────────────────────────────────────
def build_dashboard_for(uid: int, pname: str) -> pd.DataFrame:
    from datetime import datetime
    state  = _get_user_state(uid)
    with _users_lock:
        if pname not in state["portfolios"]:
            return pd.DataFrame()
        p      = state["portfolios"][pname]
        df_raw = p["df"].drop(
            columns=[c for c in ["현재가", "수익률(%)", "등락률(%)", "USD_KRW"] if c in p["df"].columns]
        ).copy()
    df = fetch_prices(df_raw)   # 락 밖에서 네트워크 IO
    usd_krw = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns and len(df) > 0 else 1370.0
    save_snapshot(uid, pname, df, usd_krw)
    with _users_lock:
        if pname not in state["portfolios"]:
            return df
        state["portfolios"][pname]["df"]          = df
        state["portfolios"][pname]["last_update"] = datetime.now(KST)
        save_portfolios(uid, state["portfolios"], state["active_pname"])
    return df


def _build_dashboard_bg(uid: int, pname: str) -> None:
    """백그라운드 스레드용 wrapper — 완료 후 _building에서 제거."""
    try:
        build_dashboard_for(uid, pname)
    except Exception as e:
        log.error(f"빌드 실패 uid={uid} pname={pname}: {e}", exc_info=True)
        with _build_lock:
            _building.discard((uid, pname))
            _hist_check.pop((uid, pname), None)
    else:
        with _build_lock:
            _building.discard((uid, pname))
            _hist_check.pop((uid, pname), None)


def _trigger_build_if_needed(uid: int, pname: str) -> None:
    """오늘 아직 빌드하지 않았고, 현재 빌드 중이 아닐 때만 스레드 1개 생성."""
    from datetime import datetime
    today = datetime.now(KST).strftime("%Y-%m-%d")
    key   = (uid, pname)
    with _build_lock:
        if _hist_check.get(key) == today or key in _building:
            return
        _building.add(key)
        _hist_check[key] = today  # 스레드 시작 전에 기록 (중복 방지)
    threading.Thread(target=_build_dashboard_bg, args=(uid, pname), daemon=True).start()


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

    existing = _find_existing_tunnel()
    if existing:
        _state.public_url = existing
        log.info(f"🌐 기존 ngrok 터널 재사용: {_state.public_url}")
        return _state.public_url

    ngrok_conf.get_default().auth_token = NGROK_TOKEN
    for attempt in range(10):
        try:
            tunnel = ngrok.connect(FLASK_PORT, "http")
            _state.public_url = tunnel.public_url.replace("http://", "https://")
            log.info(f"🌐 ngrok URL: {_state.public_url}")
            return _state.public_url
        except (PyngrokNgrokHTTPError, PyngrokNgrokError) as e:
            if ("already online" in str(e) or "ERR_NGROK_108" in str(e)) and attempt < 9:
                log.info(f"ngrok 세션 해제 대기 중... (20초, {attempt+1}/10)")
                time.sleep(20)
            else:
                raise
    return _state.public_url
