from __future__ import annotations
import json
import os
import tempfile
from datetime import date

from portfolio_bot.storage.portfolio import _user_dir, _safe_pname
from portfolio_bot.state import _get_cashflow_lock


def _cashflow_path(uid: int, pname: str) -> str:
    return os.path.join(_user_dir(uid), f"cashflow_{_safe_pname(pname)}.json")


def save_cashflow(uid: int, pname: str, records: list):
    fpath = _cashflow_path(uid, pname)
    dirpath = os.path.dirname(fpath)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dirpath, delete=False, suffix=".tmp") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        tmp_path = f.name
    os.replace(tmp_path, fpath)


def load_cashflow(uid: int, pname: str) -> list:
    fpath = _cashflow_path(uid, pname)
    if not os.path.exists(fpath):
        return []
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def add_cashflow(uid: int, pname: str, type_: str, amount: float, memo: str):
    # 지연 import — cashflow ↔ history circular import 방지
    from portfolio_bot.storage.history import load_history
    lock = _get_cashflow_lock(uid, pname)
    with lock:
        records = load_cashflow(uid, pname)
        history = load_history(uid, pname)
        current_nav = 1000.0
        if history:
            last_date = sorted(history.keys())[-1]
            current_nav = history[last_date].get("nav", 1000.0)
        records.append({
            "date":   date.today().isoformat(),
            "type":   type_,
            "amount": amount,
            "memo":   memo,
            "nav":    current_nav,
        })
        save_cashflow(uid, pname, records)


def get_net_investment(uid: int, pname: str) -> float:
    records = load_cashflow(uid, pname)
    return (
        sum(r["amount"] for r in records if r["type"] == "in")
        - sum(r["amount"] for r in records if r["type"] == "out")
    )


def compute_nav_units(uid: int, pname: str, total_assets_krw: float) -> tuple:
    """
    cashflow 기록을 기반으로 현재 nav(기준가)와 units(좌수)를 계산.
    total_assets_krw: 현재 총 평가금액(주식 + 현금), KRW 환산
    반환: (nav, units)
    """
    records = load_cashflow(uid, pname)
    if not records:
        return 1000.0, 0.0

    units = 0.0
    for cf in sorted(records, key=lambda x: (x["date"], 0 if x["type"] == "in" else 1)):
        cf_nav = cf.get("nav", 1000.0)
        if cf_nav <= 0:
            cf_nav = 1000.0
        if cf["type"] == "in":
            units += cf["amount"] / cf_nav
        else:
            units -= cf["amount"] / cf_nav

    if units <= 0:
        return 1000.0, 0.0

    nav = total_assets_krw / units
    return round(nav, 6), round(units, 6)


def compute_combined_nav(uid: int, pnames: list, total_assets_krw: float) -> tuple:
    """
    여러 포트폴리오의 cashflow를 병합해 통합 NAV를 계산.
    모든 cashflow를 날짜순 병합 후 단일 풀로 처리.
    반환: (nav, units)
    """
    all_records = []
    for pname in pnames:
        all_records.extend(load_cashflow(uid, pname))

    if not all_records:
        return 1000.0, 0.0

    units = 0.0
    for cf in sorted(all_records, key=lambda x: (x["date"], 0 if x["type"] == "in" else 1)):
        cf_nav = cf.get("nav", 1000.0)
        if cf_nav <= 0:
            cf_nav = 1000.0
        if cf["type"] == "in":
            units += cf["amount"] / cf_nav
        else:
            units -= cf["amount"] / cf_nav

    if units <= 0:
        return 1000.0, 0.0

    nav = total_assets_krw / units
    return round(nav, 6), round(units, 6)
