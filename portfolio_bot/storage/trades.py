from __future__ import annotations
import json
import os
import tempfile
from datetime import datetime

from portfolio_bot.storage.portfolio import _user_dir, _safe_pname


def _trades_path(uid: int, pname: str) -> str:
    return os.path.join(_user_dir(uid), f"trades_{_safe_pname(pname)}.json")


def load_trades(uid: int, pname: str) -> list:
    fpath = _trades_path(uid, pname)
    if not os.path.exists(fpath):
        return []
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_trade(uid: int, pname: str, trade_type: str, name: str, qty: float, price: float,
               display_avg=None):
    """
    매수: price = 매수단가, display_avg = 가중평균 (또는 None)
    매도: price = 매도단가, display_avg = 기존 매수 평단가 (old_avg)
    realized_pnl은 매도 타입일 때만 자동 계산
    """
    _sell_types = ("일부매도", "전량매도", "sell")
    fpath   = _trades_path(uid, pname)
    dirpath = os.path.dirname(fpath)
    os.makedirs(dirpath, exist_ok=True)
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception:
        records = []
    record = {
        "date":   datetime.now().strftime("%Y-%m-%d"),
        "time":   datetime.now().strftime("%H:%M"),
        "type":   trade_type,
        "name":   name,
        "qty":    round(qty, 6),
        "avg":    display_avg if display_avg is not None else price,
        "amount": round(qty * price, 2),
    }
    if trade_type in _sell_types and display_avg is not None:
        # price = 매도단가, display_avg = 매수 평단가
        record["realized_pnl"] = round(qty * (price - display_avg), 2)
    records.append(record)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                      dir=dirpath, delete=False, suffix=".tmp") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        tmp_path = f.name
    os.replace(tmp_path, fpath)


def compute_realized_pnl(uid: int, pname: str) -> tuple:
    """
    거래 기록에서 실현 손익 계산.
    realized_pnl 필드가 있는 거래만 집계 (기존 기록은 skip).
    반환: (total_realized: float, per_stock: {name: float})
    """
    trades = load_trades(uid, pname)
    total_realized = 0.0
    per_stock: dict = {}
    for t in trades:
        if t.get("type") not in ("일부매도", "전량매도", "sell"):
            continue
        realized = t.get("realized_pnl")
        if realized is None:
            continue   # realized_pnl 없는 기존 기록 skip
        total_realized += realized
        name = t.get("name", "")
        per_stock[name] = round(per_stock.get(name, 0.0) + realized, 2)
    return round(total_realized, 2), per_stock
