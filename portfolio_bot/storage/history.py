from __future__ import annotations
import json
import os
import tempfile
from datetime import date

import pandas as pd

from portfolio_bot.storage.portfolio import _user_dir, _safe_pname
from portfolio_bot.state import _get_history_lock


def _history_path(uid: int, pname: str) -> str:
    return os.path.join(_user_dir(uid), f"history_{_safe_pname(pname)}.json")


def save_snapshot(uid: int, pname: str, df: pd.DataFrame, usd_krw: float, force: bool = False):
    lock = _get_history_lock(uid, pname)
    with lock:
        _save_snapshot_inner(uid, pname, df, usd_krw, force)


def _save_snapshot_inner(uid: int, pname: str, df: pd.DataFrame, usd_krw: float, force: bool = False):
    # 지연 import — history ↔ cashflow circular import 방지
    from portfolio_bot.storage.cashflow import get_net_investment, compute_nav_units

    fpath   = _history_path(uid, pname)
    history = {}
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}

    today = date.today().isoformat()
    if today in history and not force:
        return  # 당일 이미 저장됨, skip

    stock_eval_krw = 0.0
    total_buy      = 0.0
    positions      = {}

    for _, r in df.iterrows():
        currency   = str(r.get("통화", "KRW")).upper()
        multiplier = usd_krw if currency == "USD" else 1.0
        qty        = float(r["수량"]) if "수량" in r.index and pd.notna(r.get("수량")) else 0.0
        avg        = float(r["평단가"])
        cur        = r.get("현재가")
        cur_price  = float(cur) if pd.notna(cur) else avg

        stock_eval_krw += cur_price * qty * multiplier
        total_buy      += avg * qty * multiplier

        ret = r.get("수익률(%)")
        positions[str(r["종목명"])] = {
            "return": float(ret) if pd.notna(ret) else 0.0,
            "weight": float(r["비중(%)"]),
        }

    net_investment   = get_net_investment(uid, pname)
    cash_krw         = max(0.0, net_investment - total_buy) if net_investment > 0 else 0.0
    total_assets     = stock_eval_krw + cash_krw
    total_return_pct = (stock_eval_krw - total_buy) / total_buy * 100 if total_buy > 0 else 0.0
    mwr = (total_assets - net_investment) / net_investment * 100 if net_investment > 0 else None
    nav, units = compute_nav_units(uid, pname, total_assets)
    nav_return = (nav / 1000.0 - 1) * 100

    history[today] = {
        "total_assets":   round(total_assets, 2),
        "total_return":   round(total_return_pct, 4),
        "positions":      positions,
        "net_investment": round(net_investment, 2),
        "mwr":            round(mwr, 4) if mwr is not None else None,
        "nav":            None if (nav != nav) else round(nav, 6),
        "nav_return":     None if (nav_return != nav_return) else round(nav_return, 4),
    }

    dirpath = os.path.dirname(fpath)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dirpath, delete=False, suffix=".tmp") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
        tmp_path = f.name
    os.replace(tmp_path, fpath)


def load_history(uid: int, pname: str) -> dict:
    fpath = _history_path(uid, pname)
    if not os.path.exists(fpath):
        return {}
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
