"""
storage.py  ─  멀티 포트폴리오 데이터 영구 저장/로드
  - portfolios.json        : 전체 포트폴리오 메타 + df
  - history_{pname}.json   : 포트폴리오별 날짜 스냅샷
  - cashflow_{pname}.json  : 포트폴리오별 자금 기록
"""
from __future__ import annotations
import json
import os
from datetime import datetime, date
import pandas as pd

DATA_DIR        = os.path.join(os.path.dirname(__file__), "data")
PORTFOLIOS_FILE = os.path.join(DATA_DIR, "portfolios.json")
os.makedirs(DATA_DIR, exist_ok=True)

_NUMERIC_COLS = ["비중(%)", "평단가", "수량", "현재가", "수익률(%)", "등락률(%)", "USD_KRW"]
_EMPTY_COLS   = ["종목명", "국가", "비중(%)", "평단가", "수량", "통화"]


# ─── 내부 헬퍼 ───────────────────────────────────────
def _history_path(pname: str) -> str:
    return os.path.join(DATA_DIR, f"history_{pname}.json")

def _cashflow_path(pname: str) -> str:
    return os.path.join(DATA_DIR, f"cashflow_{pname}.json")

def _raw() -> dict:
    if not os.path.exists(PORTFOLIOS_FILE):
        return {"active": "", "next_id": 1, "items": {}}
    try:
        with open(PORTFOLIOS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active": "", "next_id": 1, "items": {}}

def _save_raw(data: dict):
    with open(PORTFOLIOS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

def _df_from_records(records: list) -> pd.DataFrame:
    df = pd.DataFrame(records) if records else pd.DataFrame(columns=_EMPTY_COLS)
    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ─── 구버전 단일 포트폴리오 마이그레이션 ─────────────
def _migrate():
    if os.path.exists(PORTFOLIOS_FILE):
        return
    old_file = os.path.join(DATA_DIR, "portfolio.json")
    if not os.path.exists(old_file):
        return
    try:
        with open(old_file, "r", encoding="utf-8") as f:
            old = json.load(f)
        pname = "p1"
        raw = {
            "active":  pname,
            "next_id": 2,
            "items": {
                pname: {
                    "name":        old.get("name", "기본 포트폴리오"),
                    "last_update": old.get("last_update"),
                    "df":          old.get("df", []),
                }
            },
        }
        _save_raw(raw)
        # 파일 마이그레이션
        for old_name, new_name in [
            ("cashflow.json",  f"cashflow_{pname}.json"),
            ("history.json",   f"history_{pname}.json"),
        ]:
            src = os.path.join(DATA_DIR, old_name)
            dst = os.path.join(DATA_DIR, new_name)
            if os.path.exists(src) and not os.path.exists(dst):
                os.rename(src, dst)
        print(f"✅ portfolio.json → portfolios.json 마이그레이션 완료")
    except Exception as e:
        print(f"⚠️  마이그레이션 오류: {e}")


# ─── 포트폴리오 로드/저장 ─────────────────────────────
def load_portfolios() -> tuple[dict, str]:
    """(portfolios dict, active_pname) 반환. 없으면 기본 포트폴리오 생성."""
    _migrate()
    raw = _raw()
    items = {}
    for pname, p in raw.get("items", {}).items():
        last_update = None
        if p.get("last_update"):
            try:
                last_update = datetime.fromisoformat(p["last_update"])
            except Exception:
                pass
        items[pname] = {
            "name":        p.get("name", pname),
            "last_update": last_update,
            "df":          _df_from_records(p.get("df", [])),
        }

    if not items:
        pname = "p1"
        items[pname] = {
            "name":        "기본 포트폴리오",
            "last_update": None,
            "df":          pd.DataFrame(columns=_EMPTY_COLS),
        }
        raw["active"]  = pname
        raw["next_id"] = 2
        raw["items"]   = {"p1": {"name": "기본 포트폴리오", "last_update": None, "df": []}}
        _save_raw(raw)

    active = raw.get("active", "")
    if active not in items:
        active = next(iter(items))

    return items, active


def save_portfolios(portfolios: dict, active_pname: str):
    """portfolios dict + active → JSON 저장"""
    raw = _raw()
    raw["active"] = active_pname
    out = {}
    for pname, p in portfolios.items():
        out[pname] = {
            "name":        p.get("name", pname),
            "last_update": p["last_update"].isoformat() if p.get("last_update") else None,
            "df":          p["df"].to_dict(orient="records") if p.get("df") is not None else [],
        }
    raw["items"] = out
    _save_raw(raw)


def create_portfolio(name: str) -> str:
    """새 포트폴리오 생성, pname 반환"""
    raw = _raw()
    next_id = raw.get("next_id", 1)
    pname   = f"p{next_id}"
    raw["next_id"] = next_id + 1
    if "items" not in raw:
        raw["items"] = {}
    raw["items"][pname] = {"name": name, "last_update": None, "df": []}
    _save_raw(raw)
    return pname


def rename_portfolio(pname: str, new_name: str):
    raw = _raw()
    if pname in raw.get("items", {}):
        raw["items"][pname]["name"] = new_name
        _save_raw(raw)


def delete_portfolio(pname: str) -> str:
    """포트폴리오 삭제. 새 active pname 반환."""
    raw = _raw()
    items = raw.get("items", {})
    if pname in items:
        del items[pname]
    raw["items"] = items
    # 관련 파일 삭제
    for path in [_history_path(pname), _cashflow_path(pname)]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
    # active 갱신
    if raw.get("active") == pname:
        remaining = list(items.keys())
        raw["active"] = remaining[0] if remaining else ""
    _save_raw(raw)
    return raw.get("active", "")


# ─── 히스토리 스냅샷 ──────────────────────────────────
def save_snapshot(pname: str, df: pd.DataFrame, usd_krw: float):
    fpath   = _history_path(pname)
    history = {}
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}

    today          = date.today().isoformat()
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

    net_investment   = get_net_investment(pname)
    cash_krw         = max(0.0, net_investment - stock_eval_krw) if net_investment > 0 else 0.0
    total_assets     = stock_eval_krw + cash_krw
    total_return_pct = (stock_eval_krw - total_buy) / total_buy * 100 if total_buy > 0 else 0.0
    mwr = (total_assets - net_investment) / net_investment * 100 if net_investment > 0 else None

    history[today] = {
        "total_assets":   round(total_assets, 2),
        "total_return":   round(total_return_pct, 4),
        "positions":      positions,
        "net_investment": round(net_investment, 2),
        "mwr":            round(mwr, 4) if mwr is not None else None,
    }

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_history(pname: str) -> dict:
    fpath = _history_path(pname)
    if not os.path.exists(fpath):
        return {}
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ─── 자금 기록 ────────────────────────────────────────
def save_cashflow(pname: str, records: list):
    with open(_cashflow_path(pname), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def load_cashflow(pname: str) -> list:
    fpath = _cashflow_path(pname)
    if not os.path.exists(fpath):
        return []
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def add_cashflow(pname: str, type_: str, amount: float, memo: str):
    records = load_cashflow(pname)
    records.append({
        "date":   date.today().isoformat(),
        "type":   type_,
        "amount": amount,
        "memo":   memo,
    })
    save_cashflow(pname, records)


def get_net_investment(pname: str) -> float:
    records = load_cashflow(pname)
    return (
        sum(r["amount"] for r in records if r["type"] == "in")
        - sum(r["amount"] for r in records if r["type"] == "out")
    )
