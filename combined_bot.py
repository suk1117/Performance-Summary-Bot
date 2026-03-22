"""
combined_bot.py - 전체 포트폴리오 봇 (단일 파일) - 멀티유저
storage + price_fetcher + html_builder + bot 통합
"""
from __future__ import annotations

# =======================================================
# storage.py
# =======================================================
import json
import os
import secrets as _secrets
from datetime import datetime, date
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

_NUMERIC_COLS = ["비중(%)", "평단가", "수량", "현재가", "수익률(%)", "등락률(%)", "USD_KRW"]
_EMPTY_COLS   = ["종목명", "국가", "비중(%)", "평단가", "수량", "통화"]


# ─── 내부 헬퍼 ────────────────────────────────────────
def _safe_pname(pname: str) -> str:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]+", pname):
        raise ValueError(f"잘못된 포트폴리오 ID: {pname!r}")
    return pname

def _user_dir(uid: int) -> str:
    """data/user_{uid}/ 생성 후 경로 반환"""
    path = os.path.join(DATA_DIR, f"user_{uid}")
    os.makedirs(path, exist_ok=True)
    return path

def _portfolios_file(uid: int) -> str:
    return os.path.join(_user_dir(uid), "portfolios.json")

def _history_path(uid: int, pname: str) -> str:
    return os.path.join(_user_dir(uid), f"history_{_safe_pname(pname)}.json")

def _cashflow_path(uid: int, pname: str) -> str:
    return os.path.join(_user_dir(uid), f"cashflow_{_safe_pname(pname)}.json")

def _raw(uid: int) -> dict:
    fpath = _portfolios_file(uid)
    if not os.path.exists(fpath):
        return {"active": "", "next_id": 1, "items": {}}
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active": "", "next_id": 1, "items": {}}

def _save_raw(uid: int, data: dict):
    with open(_portfolios_file(uid), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

def _df_from_records(records: list) -> pd.DataFrame:
    df = pd.DataFrame(records) if records else pd.DataFrame(columns=_EMPTY_COLS)
    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ─── 토큰 관리 ────────────────────────────────────────
def get_user_token(uid: int) -> str:
    """uid별 URL 토큰 반환. 없으면 생성 후 저장."""
    raw = _raw(uid)
    token = raw.get("token", "")
    if not token:
        token = _secrets.token_urlsafe(16)
        raw["token"] = token
        _save_raw(uid, raw)
    return token


# ─── 구버전 마이그레이션 ──────────────────────────────
def _migrate(uid: int):
    """기존 data/portfolios.json → data/user_{uid}/portfolios.json"""
    dst = _portfolios_file(uid)
    if os.path.exists(dst):
        return
    import shutil
    # 멀티 포트폴리오 구버전
    old_portfolios = os.path.join(DATA_DIR, "portfolios.json")
    if os.path.exists(old_portfolios):
        try:
            shutil.copy2(old_portfolios, dst)
            migrated = [old_portfolios]
            for fname in os.listdir(DATA_DIR):
                if fname.startswith("history_") or fname.startswith("cashflow_"):
                    src = os.path.join(DATA_DIR, fname)
                    d   = os.path.join(_user_dir(uid), fname)
                    if not os.path.exists(d):
                        shutil.copy2(src, d)
                    migrated.append(src)
            # 마이그레이션 완료 후 구버전 파일 삭제 (다른 유저에게 복사되지 않도록)
            for f in migrated:
                try:
                    os.remove(f)
                except Exception:
                    pass
            print(f"✅ 기존 데이터 → data/user_{uid}/ 마이그레이션 완료")
        except Exception as e:
            print(f"⚠️  마이그레이션 오류: {e}")
        return
    # 단일 포트폴리오 구버전
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
        _save_raw(uid, raw)
        migrated = [old_file]
        for old_name, new_name in [
            ("cashflow.json", f"cashflow_{pname}.json"),
            ("history.json",  f"history_{pname}.json"),
        ]:
            src = os.path.join(DATA_DIR, old_name)
            d   = os.path.join(_user_dir(uid), new_name)
            if os.path.exists(src) and not os.path.exists(d):
                shutil.copy2(src, d)
                migrated.append(src)
        # 마이그레이션 완료 후 구버전 파일 삭제
        for f in migrated:
            try:
                os.remove(f)
            except Exception:
                pass
        print(f"✅ portfolio.json → data/user_{uid}/ 마이그레이션 완료")
    except Exception as e:
        print(f"⚠️  마이그레이션 오류: {e}")


# ─── 포트폴리오 로드/저장 ─────────────────────────────
def load_portfolios(uid: int) -> tuple[dict, str]:
    _migrate(uid)
    raw = _raw(uid)
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
        _save_raw(uid, raw)
    active = raw.get("active", "")
    if active not in items:
        active = next(iter(items))
    return items, active


def save_portfolios(uid: int, portfolios: dict, active_pname: str):
    raw = _raw(uid)
    raw["active"] = active_pname
    out = {}
    for pname, p in portfolios.items():
        out[pname] = {
            "name":        p.get("name", pname),
            "last_update": p["last_update"].isoformat() if p.get("last_update") else None,
            "df":          p["df"].to_dict(orient="records") if p.get("df") is not None else [],
        }
    raw["items"] = out
    _save_raw(uid, raw)


def create_portfolio(uid: int, name: str) -> str:
    raw = _raw(uid)
    next_id = raw.get("next_id", 1)
    pname   = f"p{next_id}"
    raw["next_id"] = next_id + 1
    if "items" not in raw:
        raw["items"] = {}
    raw["items"][pname] = {"name": name, "last_update": None, "df": []}
    _save_raw(uid, raw)
    return pname


def rename_portfolio(uid: int, pname: str, new_name: str):
    raw = _raw(uid)
    if pname in raw.get("items", {}):
        raw["items"][pname]["name"] = new_name
        _save_raw(uid, raw)


def delete_portfolio(uid: int, pname: str) -> str:
    raw = _raw(uid)
    items = raw.get("items", {})
    if pname in items:
        del items[pname]
    raw["items"] = items
    for path in [_history_path(uid, pname), _cashflow_path(uid, pname)]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
    if raw.get("active") == pname:
        remaining = list(items.keys())
        raw["active"] = remaining[0] if remaining else ""
    _save_raw(uid, raw)
    return raw.get("active", "")


# ─── 히스토리 스냅샷 ──────────────────────────────────
def save_snapshot(uid: int, pname: str, df: pd.DataFrame, usd_krw: float):
    fpath   = _history_path(uid, pname)
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

    net_investment   = get_net_investment(uid, pname)
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


def load_history(uid: int, pname: str) -> dict:
    fpath = _history_path(uid, pname)
    if not os.path.exists(fpath):
        return {}
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ─── 자금 기록 ────────────────────────────────────────
def save_cashflow(uid: int, pname: str, records: list):
    with open(_cashflow_path(uid, pname), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


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
    records = load_cashflow(uid, pname)
    records.append({
        "date":   date.today().isoformat(),
        "type":   type_,
        "amount": amount,
        "memo":   memo,
    })
    save_cashflow(uid, pname, records)


def get_net_investment(uid: int, pname: str) -> float:
    records = load_cashflow(uid, pname)
    return (
        sum(r["amount"] for r in records if r["type"] == "in")
        - sum(r["amount"] for r in records if r["type"] == "out")
    )

# =======================================================
# price_fetcher.py
# =======================================================
import logging
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
}

_kr_ticker_cache: dict[str, str] = {}
_us_exchange_cache: dict[str, str] = {}


def _search_kr_ticker(name: str) -> str | None:
    if name in _kr_ticker_cache:
        return _kr_ticker_cache[name]
    try:
        url = "https://ac.stock.naver.com/ac"
        params = {"q": name, "q_enc": "UTF-8", "target": "stock,index,marketindicator"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=5)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        for item in items:
            if item.get("name") == name and item.get("nationCode") == "KOR":
                code = item["code"]
                _kr_ticker_cache[name] = code
                log.info(f"티커 검색: {name} → {code}")
                return code
        for item in items:
            if item.get("nationCode") == "KOR":
                code = item["code"]
                _kr_ticker_cache[name] = code
                log.info(f"티커 검색: {name} → {code} (첫 번째 결과)")
                return code
    except Exception as e:
        log.warning(f"티커 검색 실패 ({name}): {e}")
    return None


def _naver_stock_price(code: str) -> tuple[float | None, float | None]:
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        r   = requests.get(url, headers=HEADERS, timeout=5)
        r.raise_for_status()
        data = r.json()
        price_str = (
            data.get("currentPrice")
            or data.get("closePrice")
            or data.get("stockEndPrice")
        )
        price = float(str(price_str).replace(",", "")) if price_str else None
        change = data.get("fluctuationsRatio")
        if change is not None:
            try:
                change = float(change)
            except (ValueError, TypeError):
                change = None
        return price, change
    except Exception as e:
        log.warning(f"네이버 가격 조회 실패 ({code}): {e}")
    return None, None


def get_kr_price(name: str) -> tuple[float | None, float | None]:
    ticker = _search_kr_ticker(name)
    if not ticker:
        return None, None
    return _naver_stock_price(ticker)


def get_us_price(ticker: str) -> tuple[float | None, float | None]:
    try:
        import yfinance as yf
        t    = yf.Ticker(ticker)
        info = t.fast_info
        price = getattr(info, "last_price", None)
        prev  = getattr(info, "regular_market_previous_close", None)
        if price is None:
            hist = t.history(period="2d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                if len(hist) >= 2:
                    prev = float(hist["Close"].iloc[-2])
        change = round((float(price) - float(prev)) / float(prev) * 100, 2) if price and prev else None
        if price:
            log.info(f"US 가격 조회: {ticker} = ${float(price):,.2f}")
            return float(price), change
    except Exception as e:
        log.warning(f"US 가격 조회 실패 ({ticker}): {e}")
    return None, None


def get_usd_krw() -> float:
    try:
        import yfinance as yf
        hist = yf.Ticker("USDKRW=X").history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        log.warning(f"get_usd_krw yfinance 실패: {e}")
    try:
        url  = "https://m.stock.naver.com/api/stock/FX_USDKRW/basic"
        r    = requests.get(url, headers=HEADERS, timeout=5)
        data = r.json()
        price_str = (
            data.get("currentPrice")
            or data.get("closePrice")
            or data.get("stockEndPrice")
        )
        if price_str:
            return float(str(price_str).replace(",", ""))
    except Exception as e:
        log.warning(f"get_usd_krw 네이버 fallback 실패: {e}")
    return 1370.0


def _fetch_one(row: dict) -> tuple[float | None, float | None]:
    name    = str(row["종목명"]).strip()
    country = str(row["국가"]).strip()
    log.info(f"  🔍 {name} ({country})")
    if country == "KR":
        return get_kr_price(name)
    elif country == "US":
        return get_us_price(name)
    return None, None


def fetch_prices(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["국가"] != "현금"].reset_index(drop=True)
    usd_krw = get_usd_krw()
    log.info(f"  💱 USD/KRW: {usd_krw:,.1f}")

    rows = df.to_dict("records")
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(_fetch_one, rows))

    current_prices = [r[0] for r in results]
    daily_changes  = [r[1] for r in results]

    returns = []
    for i, (_, row) in enumerate(df.iterrows()):
        avg   = float(row["평단가"])
        price = current_prices[i]
        if price is None or avg == 0:
            returns.append(None)
        else:
            returns.append(round((price - avg) / avg * 100, 2))

    eval_amounts = []
    for i, (_, row) in enumerate(df.iterrows()):
        currency = str(row["통화"]).upper()
        qty      = float(row["수량"]) if pd.notna(row["수량"]) else 0.0
        cp       = current_prices[i]
        avg      = float(row["평단가"])
        price    = cp if cp is not None else avg
        mult     = usd_krw if currency == "USD" else 1.0
        eval_amounts.append(price * qty * mult)

    total_eval = sum(eval_amounts)
    weights = [
        round(e / total_eval * 100, 2) if total_eval > 0 else 0.0
        for e in eval_amounts
    ]

    df = df.copy()
    df["현재가"]    = current_prices
    df["수익률(%)"] = returns
    df["등락률(%)"] = daily_changes
    df["비중(%)"]   = weights
    df["USD_KRW"]   = usd_krw
    return df

# =======================================================
# html_builder.py
# =======================================================
import json
import pandas as pd
from datetime import datetime, date, timedelta


def _build_portfolio_tabs(
    all_portfolios: dict,
    current_pname: str,
    uid: int = 0,
    token: str = "",
) -> str:
    if not all_portfolios:
        return ""
    tabs = ""
    for pname, p in all_portfolios.items():
        name = p.get("name", pname)
        name_esc = name.replace("'", "\\'")
        if pname == current_pname:
            del_btn = ""
            if len(all_portfolios) > 1:
                del_btn = (
                    f'<button onclick="deletePortfolio(\'{pname}\')" title="삭제" '
                    f'style="background:none;border:none;cursor:pointer;padding:1px 3px;'
                    f'font-size:.7rem;color:#94a3b8;line-height:1;margin-left:2px">🗑️</button>'
                )
            ren_btn = (
                f'<button onclick="openRenameModal(\'{pname}\',\'{name_esc}\')" title="이름 변경" '
                f'style="background:none;border:none;cursor:pointer;padding:1px 3px;'
                f'font-size:.7rem;color:#94a3b8;line-height:1;margin-left:4px">✏️</button>'
            )
            tabs += (
                f'<span class="tab active" style="display:inline-flex;align-items:center;cursor:default">'
                f'{name}{ren_btn}{del_btn}</span>'
            )
        else:
            tabs += f'<a href="/u/{uid}/p/{pname}?t={token}" class="tab">{name}</a>'
    tabs += (
        '<button onclick="openNewPortfolioModal()" title="새 포트폴리오" '
        'style="display:inline-flex;align-items:center;height:52px;padding:0 10px;'
        'background:none;border:none;cursor:pointer;font-size:1rem;color:#94a3b8;'
        'font-family:inherit;flex-shrink:0">＋</button>'
    )
    return tabs


def build_user_html(
    df: pd.DataFrame,
    display_name: str = "",
    cashflows: list = None,
    pname: str = "",
    all_portfolios: dict = None,
    uid: int = 0,
    token: str = "",
) -> str:
    today_str  = datetime.now().strftime("%Y.%m.%d %H:%M")
    cashflows  = cashflows or []
    pname_js   = pname or ""
    net_investment = (
        sum(c["amount"] for c in cashflows if c["type"] == "in")
        - sum(c["amount"] for c in cashflows if c["type"] == "out")
    )
    portfolio_tabs = _build_portfolio_tabs(all_portfolios or {}, pname, uid=uid, token=token)

    hist        = load_history(uid, pname) if pname else {}
    hist_dates  = sorted(hist.keys())
    hist_twr_vals = [hist[d].get("total_return") for d in hist_dates]
    hist_mwr_vals = [hist[d].get("mwr") for d in hist_dates]
    hist_dates_js = json.dumps(hist_dates)
    hist_twr_js   = json.dumps([round(v, 4) if v is not None else None for v in hist_twr_vals])
    hist_mwr_js   = json.dumps([round(v, 4) if v is not None else None for v in hist_mwr_vals])
    show_hist     = len(hist_dates) > 1

    def _period_ret(days):
        if not hist:
            return None
        sorted_dates = sorted(hist.keys())
        cur_mwr = hist[sorted_dates[-1]].get("mwr")
        if cur_mwr is None:
            return None
        target = (date.today() - timedelta(days=days)).isoformat()
        past_dates = [d for d in sorted_dates if d <= target]
        if not past_dates:
            return None
        past_mwr = hist[past_dates[-1]].get("mwr")
        if past_mwr is None:
            return None
        return round(cur_mwr - past_mwr, 2)

    _period_labels = [("1개월", 30), ("3개월", 90), ("6개월", 180), ("1년", 365), ("전체", None)]
    def _period_ret_all():
        if not hist:
            return None
        sorted_dates = sorted(hist.keys())
        first_mwr = None
        for d in sorted_dates:
            v = hist[d].get("mwr")
            if v is not None:
                first_mwr = v
                break
        cur_mwr = hist[sorted_dates[-1]].get("mwr")
        if cur_mwr is None or first_mwr is None:
            return None
        return round(cur_mwr - first_mwr, 2)

    _period_vals = []
    for _lbl, _days in _period_labels:
        if _days is None:
            _v = _period_ret_all()
        else:
            _v = _period_ret(_days)
        _period_vals.append((_lbl, _v))

    def _pret_html(lbl, val):
        if val is None:
            return (
                f'<div style="text-align:center;padding:8px 0">'
                f'<div style="font-size:.75rem;color:#94a3b8;margin-bottom:4px">{lbl}</div>'
                f'<div style="font-size:1rem;font-weight:700;color:#94a3b8">-</div>'
                f'</div>'
            )
        color = "#10b981" if val >= 0 else "#ef4444"
        sign  = "+" if val >= 0 else ""
        return (
            f'<div style="text-align:center;padding:8px 0">'
            f'<div style="font-size:.75rem;color:#94a3b8;margin-bottom:4px">{lbl}</div>'
            f'<div style="font-size:1rem;font-weight:700;color:{color}">{sign}{val:.2f}%</div>'
            f'</div>'
        )

    _period_cells = "".join(_pret_html(lbl, val) for lbl, val in _period_vals)
    period_html = (
        '<div class="card" style="margin-bottom:16px">'
        '<div class="card-title">기간별 수익률</div>'
        f'<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:4px">'
        f'{_period_cells}'
        f'</div>'
        f'</div>'
    ) if hist else ""

    PALETTE = [
        "#0ea5e9","#8b5cf6","#f59e0b","#ef4444",
        "#10b981","#f97316","#06b6d4","#84cc16","#ec4899","#6366f1",
    ]

    for col in ["수익률(%)", "등락률(%)", "현재가", "USD_KRW"]:
        if col not in df.columns:
            df = df.copy()
            df[col] = float("nan")

    usd_krw = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns and len(df) > 0 else 1370.0

    stock_eval_krw = 0.0
    total_buy      = 0.0
    for _, _r in df.iterrows():
        _mult  = usd_krw if str(_r["통화"]).upper() == "USD" else 1.0
        _qty   = float(_r["수량"]) if "수량" in _r.index and pd.notna(_r.get("수량")) else 0.0
        _cur   = _r.get("현재가")
        _price = float(_cur) if pd.notna(_cur) else float(_r["평단가"])
        stock_eval_krw += _price * _qty * _mult
        total_buy      += float(_r["평단가"]) * _qty * _mult
    total_return = (stock_eval_krw - total_buy) / total_buy * 100 if total_buy > 0 else 0.0
    cash_krw    = max(0.0, net_investment - total_buy) if net_investment > 0 else 0.0
    total_ev    = stock_eval_krw + cash_krw
    show_cash   = net_investment > 0 and cash_krw > 0
    _w_scale    = stock_eval_krw / total_ev if total_ev > 0 else 1.0
    cash_wpct   = round(cash_krw / total_ev * 100, 2) if total_ev > 0 else 0.0

    _w_main = df[df["비중(%)"] >= 1.0]
    _w_small = df[df["비중(%)"] < 1.0]
    if not _w_small.empty:
        _other = pd.DataFrame([{"종목명": "기타", "비중(%)": _w_small["비중(%)"].sum()}])
        _w_chart = pd.concat([_w_main[["종목명", "비중(%)"]], _other], ignore_index=True)
    else:
        _w_chart = _w_main[["종목명", "비중(%)"]].copy()
    name_to_idx = {name: i for i, name in enumerate(df["종목명"].tolist())}
    _w_chart = _w_chart.copy()
    _w_chart["비중(%)"] = (_w_chart["비중(%)"] * _w_scale).round(2)
    if show_cash:
        _w_chart = pd.concat(
            [_w_chart, pd.DataFrame([{"종목명": "현금", "비중(%)": cash_wpct}])],
            ignore_index=True,
        )
    wl = json.dumps(_w_chart["종목명"].tolist(), ensure_ascii=False)
    wd = json.dumps([round(v, 2) for v in _w_chart["비중(%)"].tolist()])
    wp = json.dumps([
        PALETTE[name_to_idx[n] % len(PALETTE)] if n in name_to_idx else "#94a3b8"
        for n in _w_chart["종목명"].tolist()
    ])

    cg = df.groupby("국가")["비중(%)"].sum().reset_index()
    _cg_total = cg["비중(%)"].sum()
    if _cg_total > 0:
        cg["비중(%)"] = (cg["비중(%)"] / _cg_total * 100 * _w_scale).round(2)
    _country_color_list = []
    for c in cg["국가"].tolist():
        first_stock = df[df["국가"] == c]["종목명"].iloc[0] if not df[df["국가"] == c].empty else None
        idx = name_to_idx.get(first_stock, len(_country_color_list)) if first_stock else len(_country_color_list)
        _country_color_list.append(PALETTE[idx % len(PALETTE)])
    if show_cash:
        cg = pd.concat(
            [cg, pd.DataFrame([{"국가": "현금", "비중(%)": cash_wpct}])],
            ignore_index=True,
        )
        _country_color_list.append("#94a3b8")
    cl = json.dumps(cg["국가"].tolist(), ensure_ascii=False)
    cd = json.dumps(cg["비중(%)"].tolist())
    country_colors = json.dumps(_country_color_list)

    ret_df = (
        df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
        .sort_values("수익률(%)", ascending=True)
    )
    rl = json.dumps(ret_df["종목명"].tolist(), ensure_ascii=False)
    rd = json.dumps(ret_df["수익률(%)"].tolist())
    rc = json.dumps([PALETTE[name_to_idx.get(n, 0) % len(PALETTE)] for n in ret_df["종목명"].tolist()])
    ret_count    = len(ret_df)
    ret_chart_h  = max(160, ret_count * 56)

    total_eval = 0.0
    name_to_color = {name: PALETTE[i % len(PALETTE)] for i, name in enumerate(df["종목명"].tolist())}
    table_rows = ""

    for _, r in df.iterrows():
        ret_val    = r["수익률(%)"]
        chg_val    = r["등락률(%)"]
        cur_price  = r.get("현재가")
        avg        = float(r["평단가"])
        weight     = float(r["비중(%)"])
        currency   = str(r["통화"]).upper()
        flag       = {"KR": "🇰🇷 한국", "US": "🇺🇸 미국", "현금": "💵 현금"}.get(r["국가"], f"🌐 {r['국가']}")
        color      = name_to_color.get(r["종목명"], "#64748b")
        name       = r["종목명"]
        initial    = name[0].upper()

        if pd.isna(ret_val):
            ret_str, ret_col = "—", "#94a3b8"
        elif ret_val > 0:
            ret_str, ret_col = f"+{ret_val:.2f}%", "#16a34a"
        elif ret_val < 0:
            ret_str, ret_col = f"{ret_val:.2f}%", "#dc2626"
        else:
            ret_str, ret_col = "0.00%", "#64748b"

        if pd.isna(chg_val):
            chg_str, chg_col = "—", "#94a3b8"
        elif chg_val > 0:
            chg_str, chg_col = f"+{chg_val:.2f}%", "#16a34a"
        elif chg_val < 0:
            chg_str, chg_col = f"{chg_val:.2f}%", "#dc2626"
        else:
            chg_str, chg_col = "0.00%", "#64748b"

        cur_str = (f"₩{cur_price:,.0f}" if currency == "KRW" else f"${cur_price:,.2f}") if pd.notna(cur_price) else "—"
        avg_str = f"₩{avg:,.0f}" if currency == "KRW" else f"${avg:,.2f}"

        multiplier = usd_krw if currency == "USD" else 1.0
        qty = float(r["수량"]) if "수량" in r.index and pd.notna(r["수량"]) else None

        if qty is not None:
            buy_krw  = avg * qty * multiplier
            buy_str  = f"₩{buy_krw:,.0f}" if currency == "KRW" else f"${avg*qty:,.2f}"
            if pd.notna(cur_price):
                eval_krw   = float(cur_price) * qty * multiplier
                total_eval += eval_krw
                eval_str   = f"₩{eval_krw:,.0f}" if currency == "KRW" else f"${float(cur_price)*qty:,.2f}"
            else:
                eval_str = "—"
        else:
            buy_str = eval_str = "—"

        import json as _json
        _ed = _json.dumps({"name": name, "country": r["국가"], "qty": qty or 0, "avg": avg, "weight": weight})
        _name_js = _json.dumps(name, ensure_ascii=False).replace('"', '&quot;')
        edit_btns = (
            f'<td style="text-align:right;white-space:nowrap">'
            f'<button onclick=\'openEditModal({_ed})\' style="background:none;border:1px solid var(--border);'
            f'border-radius:6px;padding:4px 8px;cursor:pointer;font-size:.75rem;color:var(--secondary);margin-right:4px">✏️</button>'
            f'<button onclick="deleteStock({_name_js})" style="background:none;border:1px solid #fecaca;'
            f'border-radius:6px;padding:4px 8px;cursor:pointer;font-size:.75rem;color:#dc2626">🗑️</button>'
            f'</td>'
        )

        table_rows += f"""<tr>
          <td>
            <div style="display:flex;align-items:center;gap:10px">
              <div style="width:32px;height:32px;border-radius:50%;background:{color};
                display:flex;align-items:center;justify-content:center;
                font-weight:700;font-size:.8rem;color:#fff;flex-shrink:0">{initial}</div>
              <div>
                <div style="font-weight:600;color:#0f172a;font-size:.88rem">{name}</div>
                <div style="font-size:.72rem;color:#94a3b8">{flag}</div>
              </div>
            </div>
          </td>
          <td class="num">{avg_str}</td>
          <td class="num" style="color:#0f172a;font-weight:600">{cur_str}</td>
          <td class="num" style="color:{chg_col};font-weight:700">{chg_str}</td>
          <td class="num" style="color:{ret_col};font-weight:600">{ret_str}</td>
          <td class="num">{weight * _w_scale:.1f}%</td>
          <td class="num">{buy_str}</td>
          <td class="num">{eval_str}</td>
          {edit_btns}
        </tr>"""

    total_pnl     = stock_eval_krw - total_buy
    total_pnl_pct = (total_pnl / total_buy * 100) if total_buy > 0 else 0.0
    total_eval   += cash_krw
    cash_weight   = round(cash_krw / total_ev * 100, 1) if total_ev > 0 else 0.0
    stock_count   = len(df)

    daily_pnl = 0.0
    for _, r in df.iterrows():
        chg = r.get("등락률(%)")
        cp  = r.get("현재가")
        if pd.isna(chg) or chg is None or pd.isna(cp) or cp is None:
            continue
        currency = str(r["통화"]).upper()
        qty      = float(r["수량"]) if "수량" in r.index and pd.notna(r["수량"]) else 0.0
        mult     = usd_krw if currency == "USD" else 1.0
        prev_price   = float(cp) / (1 + float(chg) / 100)
        daily_pnl   += (float(cp) - prev_price) * qty * mult
    daily_pnl_pct = (daily_pnl / stock_eval_krw * 100) if stock_eval_krw > 0 else 0.0

    def fmt_krw(v: float) -> str:
        if abs(v) >= 1e8:
            return f"₩{v/1e8:,.2f}억"
        if abs(v) >= 1e4:
            return f"₩{v/1e4:,.0f}만"
        return f"₩{v:,.0f}"

    if show_cash:
        table_rows += (
            f'<tr>'
            f'<td><div style="font-weight:600;color:#0f172a;font-size:.88rem;padding:4px 0">💵 현금</div></td>'
            f'<td class="num">—</td>'
            f'<td class="num" style="color:#0f172a;font-weight:600">{fmt_krw(cash_krw)}</td>'
            f'<td class="num">—</td>'
            f'<td class="num">—</td>'
            f'<td class="num">{cash_weight:.1f}%</td>'
            f'<td class="num">—</td>'
            f'<td class="num">{fmt_krw(cash_krw)}</td>'
            f'<td></td>'
            f'</tr>'
        )

    net_inv_disp = fmt_krw(net_investment) if cashflows else "—"

    if cashflows:
        cf_rows = ""
        for cf in reversed(cashflows):
            t_label = "🟢 입금" if cf["type"] == "in" else "🔴 출금"
            t_color = "#16a34a" if cf["type"] == "in" else "#dc2626"
            a_str   = fmt_krw(cf["amount"])
            memo    = cf.get("memo", "")
            cf_rows += (
                f'<tr>'
                f'<td style="padding:10px">{cf["date"]}</td>'
                f'<td style="padding:10px;color:{t_color};font-weight:600">{t_label}</td>'
                f'<td class="num" style="padding:10px">{a_str}</td>'
                f'<td style="padding:10px;color:#64748b">{memo}</td>'
                f'</tr>'
            )
    else:
        cf_rows = '<tr><td colspan="4" style="text-align:center;color:#94a3b8;padding:28px">자금 기록이 없습니다</td></tr>'

    if show_hist:
        hist_chart_html = (
            '<div class="card" style="margin-bottom:16px">'
            '<div class="card-title">수익률 추이</div>'
            '<div style="position:relative;height:220px">'
            '<canvas id="histChart"></canvas>'
            '</div></div>'
        )
        hist_chart_js = f"""new Chart(document.getElementById("histChart"), {{
  type: "line",
  data: {{
    labels: {hist_dates_js},
    datasets: [
      {{
        label: "가중 수익률",
        data: {hist_twr_js},
        borderColor: "#0ea5e9",
        backgroundColor: "rgba(14,165,233,.08)",
        tension: 0.3, fill: true, pointRadius: 3, borderWidth: 2,
      }},
      {{
        label: "실제 수익률(MWR)",
        data: {hist_mwr_js},
        borderColor: "#6366f1",
        backgroundColor: "rgba(99,102,241,.04)",
        tension: 0.3, fill: false, pointRadius: 3, borderWidth: 2, spanGaps: true,
      }},
    ],
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: "top", labels: {{ boxWidth: 9, padding: 10, font: {{ size: 11 }} }} }},
      tooltip: {{
        callbacks: {{
          label: function(c) {{
            var v = c.parsed.y;
            return " " + c.dataset.label + ": " + (v == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%");
          }},
        }},
      }},
    }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ color: "#94a3b8", font: {{ size: 10 }}, maxTicksLimit: 8 }} }},
      y: {{ grid: {{ color: "#f1f5f9" }}, ticks: {{ color: "#94a3b8", callback: function(v) {{ return (v >= 0 ? "+" : "") + v + "%"; }} }} }},
    }},
  }},
}});"""
    else:
        hist_chart_html = ""
        hist_chart_js   = ""

    eval_disp      = fmt_krw(total_ev)
    pnl_disp       = fmt_krw(total_pnl)
    pnl_sign       = "+" if total_pnl >= 0 else ""
    pnl_color      = "#16a34a" if total_pnl >= 0 else "#dc2626"
    daily_disp     = fmt_krw(daily_pnl)
    daily_sign     = "+" if daily_pnl >= 0 else ""
    daily_color    = "#16a34a" if daily_pnl >= 0 else "#dc2626"
    ret_sign   = "+" if total_return >= 0 else ""
    ret_color  = "#16a34a" if total_return >= 0 else "#dc2626"
    title_name = display_name or "포트폴리오"
    action_th  = "<th></th>"
    add_btn    = (
        '<div style="display:flex;gap:8px;align-items:center">'
        f'<span class="badge">{len(df)}개 종목</span>'
        '<button id="refresh-btn" onclick="refreshPrices()" style="background:#f1f5f9;border:1px solid var(--border);'
        'border-radius:8px;padding:5px 12px;cursor:pointer;font-size:.78rem;font-weight:600;color:var(--secondary)">🔄 가격 새로고침</button>'
        '<button onclick="openAddModal()" style="background:var(--accent);border:none;'
        'border-radius:8px;padding:5px 14px;cursor:pointer;font-size:.78rem;font-weight:700;color:#fff">+ 종목 추가</button>'
        '</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title_name} · 포트폴리오</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg:#f1f5f9; --surface:#fff;
  --border:#e2e8f0; --border-subtle:#f1f5f9;
  --text:#0f172a; --secondary:#64748b; --muted:#94a3b8;
  --pos:#16a34a; --neg:#dc2626; --accent:#0ea5e9;
  --shadow:0 1px 3px rgba(0,0,0,.07),0 1px 2px rgba(0,0,0,.04);
  --shadow-md:0 4px 8px rgba(0,0,0,.06),0 2px 4px rgba(0,0,0,.04);
}}
*,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
body {{
  background:var(--bg);
  color:var(--text);
  font-family:'Noto Sans KR',sans-serif;
  min-height:100vh;
  font-size:14px;
  -webkit-font-smoothing:antialiased;
}}
.topnav {{
  background:var(--surface);
  border-bottom:1px solid var(--border);
  padding:0 28px;
  display:flex;
  align-items:center;
  height:52px;
  position:sticky;
  top:0;
  z-index:100;
  box-shadow:0 1px 0 var(--border);
}}
.brand {{
  font-weight:800;
  font-size:.95rem;
  color:var(--text);
  letter-spacing:-.01em;
  margin-right:24px;
  display:flex;
  align-items:center;
  gap:7px;
  flex-shrink:0;
}}
.brand-dot {{ width:7px; height:7px; border-radius:50%; background:var(--accent); }}
.tab {{
  display:inline-flex;
  align-items:center;
  height:52px;
  padding:0 14px;
  font-size:.85rem;
  font-weight:500;
  color:var(--secondary);
  text-decoration:none;
  border-bottom:2px solid transparent;
  transition:all .15s;
  white-space:nowrap;
}}
.tab:hover {{ color:var(--text); }}
.tab.active {{ color:var(--text); font-weight:700; border-bottom-color:var(--accent); }}
.nav-time {{ margin-left:auto; font-size:.72rem; color:var(--muted); flex-shrink:0; }}
.main {{ max-width:1160px; margin:0 auto; padding:28px 20px 48px; }}
.overview {{
  background:var(--surface);
  border-radius:14px;
  box-shadow:var(--shadow-md);
  padding:26px 30px;
  margin-bottom:16px;
  display:flex;
  align-items:center;
  gap:0;
  flex-wrap:wrap;
  row-gap:16px;
}}
.ov-main {{ flex-shrink:0; padding-right:30px; border-right:1px solid var(--border); margin-right:30px; }}
.ov-main .ov-label {{ font-size:.68rem; color:var(--muted); text-transform:uppercase; letter-spacing:.1em; margin-bottom:6px; font-weight:600; }}
.ov-main .ov-value {{ font-size:2.1rem; font-weight:700; color:var(--text); letter-spacing:-.03em; line-height:1; }}
.ov-metrics {{ display:flex; gap:0; flex-wrap:wrap; }}
.ov-metric {{ padding:0 26px; border-right:1px solid var(--border); display:flex; flex-direction:column; gap:5px; }}
.ov-metric:last-child {{ border-right:none; }}
.m-label {{ font-size:.68rem; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; font-weight:600; }}
.m-value {{ font-size:1.15rem; font-weight:700; line-height:1; }}
.m-sub {{ font-size:.72rem; color:var(--muted); }}
.charts-grid {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; margin-bottom:16px; }}
@media(max-width:1000px) {{ .charts-grid {{ grid-template-columns:1fr 1fr; }} }}
@media(max-width:640px)  {{ .charts-grid {{ grid-template-columns:1fr; }} }}
.card {{ background:var(--surface); border-radius:14px; box-shadow:var(--shadow); padding:22px; }}
.card-title {{
  font-size:.7rem; font-weight:700; color:var(--secondary);
  text-transform:uppercase; letter-spacing:.12em; margin-bottom:16px;
  display:flex; align-items:center; gap:8px;
}}
.card-title::before {{
  content:""; display:inline-block; width:3px; height:11px;
  background:var(--accent); border-radius:2px; flex-shrink:0;
}}
.table-card {{ background:var(--surface); border-radius:14px; box-shadow:var(--shadow); padding:22px; margin-bottom:16px; overflow-x:auto; }}
.table-header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; }}
.badge {{ background:#f1f5f9; color:var(--secondary); font-size:.7rem; font-weight:700; padding:3px 10px; border-radius:99px; }}
table {{ width:100%; border-collapse:collapse; }}
thead th {{ font-size:.7rem; text-transform:uppercase; letter-spacing:.07em; color:var(--muted); font-weight:700; padding:8px 10px; border-bottom:1px solid var(--border); text-align:left; }}
tbody tr {{ border-bottom:1px solid var(--border-subtle); transition:background .1s; }}
tbody tr:last-child {{ border-bottom:none; }}
tbody tr:hover {{ background:#f8fafc; }}
tbody td {{ padding:12px 10px; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.footer {{ text-align:center; padding:28px 0 4px; font-size:.65rem; color:#cbd5e1; letter-spacing:.1em; text-transform:uppercase; }}
@keyframes fadeIn {{ from {{ opacity:0; transform:translateY(10px); }} to {{ opacity:1; transform:translateY(0); }} }}
.overview {{ animation:fadeIn .3s ease both; }}
.charts-grid .card:nth-child(1) {{ animation:fadeIn .3s .04s ease both; }}
.charts-grid .card:nth-child(2) {{ animation:fadeIn .3s .08s ease both; }}
.charts-grid .card:nth-child(3) {{ animation:fadeIn .3s .12s ease both; }}
.table-card {{ animation:fadeIn .3s .16s ease both; }}
.modal-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.35); z-index:300; align-items:center; justify-content:center; }}
.modal-overlay.open {{ display:flex; }}
.modal-box {{ background:#fff; border-radius:16px; padding:28px; width:400px; max-width:92vw; box-shadow:0 20px 60px rgba(0,0,0,.15); }}
.modal-title {{ font-size:1rem; font-weight:700; color:var(--text); margin-bottom:20px; }}
.form-group {{ display:flex; flex-direction:column; gap:5px; margin-bottom:14px; }}
.form-label {{ font-size:.68rem; font-weight:700; color:var(--secondary); text-transform:uppercase; letter-spacing:.08em; }}
.form-input, .form-select {{ border:1px solid var(--border); border-radius:8px; padding:9px 12px; font-size:.88rem; color:var(--text); font-family:inherit; outline:none; width:100%; transition:border-color .15s; }}
.form-input:focus, .form-select:focus {{ border-color:var(--accent); }}
.form-row {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
.modal-actions {{ display:flex; gap:10px; justify-content:flex-end; margin-top:22px; }}
.btn-cancel {{ background:#f1f5f9; border:none; border-radius:8px; padding:8px 18px; cursor:pointer; font-size:.85rem; font-weight:600; color:var(--secondary); }}
.btn-save {{ background:var(--accent); border:none; border-radius:8px; padding:8px 20px; cursor:pointer; font-size:.85rem; font-weight:700; color:#fff; }}
.btn-save:disabled {{ opacity:.6; cursor:not-allowed; }}
</style>
</head>
<body>

<nav class="topnav">
  <div class="brand"><div class="brand-dot"></div>PORTFOLIO</div>
  {portfolio_tabs}
  <div class="nav-time">기준: {today_str}</div>
</nav>

<div class="main">
  <div class="overview">
    <div class="ov-main">
      <div class="ov-label">총 평가금액</div>
      <div class="ov-value">{eval_disp}</div>
    </div>
    <div class="ov-metrics">
      <div class="ov-metric">
        <div class="m-label">총 손익</div>
        <div class="m-value" style="color:{pnl_color}">{pnl_sign}{pnl_disp}</div>
        <div class="m-sub" style="color:{pnl_color}">{pnl_sign}{total_pnl_pct:.2f}%</div>
      </div>
      <div class="ov-metric">
        <div class="m-label">일일 손익</div>
        <div class="m-value" style="color:{daily_color}">{daily_sign}{daily_disp}</div>
        <div class="m-sub" style="color:{daily_color}">{daily_sign}{daily_pnl_pct:.2f}%</div>
      </div>
      <div class="ov-metric">
        <div class="m-label">가중 수익률</div>
        <div class="m-value" style="color:{ret_color}">{ret_sign}{total_return:.2f}%</div>
        <div class="m-sub">주식 종목 기준</div>
      </div>
      <div class="ov-metric">
        <div class="m-label">투자 종목</div>
        <div class="m-value" style="color:var(--text)">{stock_count}개</div>
        <div class="m-sub">현금 제외</div>
      </div>
      <div class="ov-metric">
        <div class="m-label">현금 비중</div>
        <div class="m-value" style="color:var(--accent)">{cash_weight:.1f}%</div>
        <div class="m-sub">전체 포트폴리오</div>
      </div>
      <div class="ov-metric">
        <div class="m-label">순 투자원금</div>
        <div class="m-value" style="color:var(--text)">{net_inv_disp}</div>
        <div class="m-sub">총입금 - 총출금</div>
      </div>
    </div>
  </div>

  <div class="charts-grid" style="grid-template-columns:1fr 1fr">
    <div class="card">
      <div class="card-title">종목별 비중</div>
      <div style="position:relative;height:220px"><canvas id="weightChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">국가별 비중</div>
      <div style="position:relative;height:220px"><canvas id="countryChart"></canvas></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-title">종목별 수익률</div>
    <div style="position:relative;height:{ret_chart_h}px"><canvas id="returnChart"></canvas></div>
  </div>

  {period_html}
  {hist_chart_html}

  <div class="table-card">
    <div class="table-header">
      <div class="card-title" style="margin-bottom:0">전체 포지션</div>
      {add_btn}
    </div>
    <table>
      <thead>
        <tr>
          <th>종목명</th><th class="num">평균단가</th><th class="num">현재가</th>
          <th class="num">일등락</th><th class="num">수익률</th><th class="num">비중</th>
          <th class="num">매수금액</th><th class="num">평가금액</th>{action_th}
        </tr>
      </thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>

  <div class="table-card" style="margin-top:16px">
    <div class="table-header">
      <div class="card-title" style="margin-bottom:0">자금 기록</div>
      <button onclick="openCashflowModal()" style="background:var(--accent);border:none;
        border-radius:8px;padding:5px 14px;cursor:pointer;font-size:.78rem;font-weight:700;color:#fff">
        ＋ 자금 기록
      </button>
    </div>
    <table>
      <thead>
        <tr><th>날짜</th><th>구분</th><th class="num">금액</th><th>메모</th></tr>
      </thead>
      <tbody>{cf_rows}</tbody>
    </table>
  </div>

  <div class="footer">Portfolio Dashboard &middot; {today_str} &middot; 투자 참고용</div>
</div>

<!-- 종목 추가/수정 모달 -->
<div class="modal-overlay" id="modal">
  <div class="modal-box">
    <div class="modal-title" id="modal-title">종목 추가</div>
    <div class="form-group" id="row-name">
      <label class="form-label">종목명</label>
      <input id="f-name" class="form-input" type="text" placeholder="예: 삼성전자, AAPL">
    </div>
    <div class="form-group">
      <label class="form-label">국가</label>
      <select id="f-country" class="form-select" onchange="onCountryChange()">
        <option value="KR">🇰🇷 한국</option>
        <option value="US">🇺🇸 미국</option>
      </select>
    </div>
    <div class="form-row" id="row-qty-avg">
      <div class="form-group" style="margin-bottom:0" id="row-qty">
        <label class="form-label">수량</label>
        <input id="f-qty" class="form-input" type="number" placeholder="0" min="0">
      </div>
      <div class="form-group" style="margin-bottom:0">
        <label class="form-label" id="label-avg">평균단가</label>
        <input id="f-avg" class="form-input" type="number" placeholder="0" min="0" step="any">
      </div>
    </div>
    <div class="form-group" id="row-cash" style="display:none">
      <label class="form-label">금액</label>
      <input id="f-cash" class="form-input" type="number" placeholder="0" min="0" step="any">
    </div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeModal()">취소</button>
      <button class="btn-save" id="btn-save" onclick="saveStock()">저장</button>
    </div>
  </div>
</div>

<!-- 새 포트폴리오 모달 -->
<div class="modal-overlay" id="new-ptab-modal">
  <div class="modal-box">
    <div class="modal-title">새 포트폴리오</div>
    <div class="form-group">
      <label class="form-label">이름</label>
      <input id="new-ptab-name" class="form-input" type="text"
        placeholder="예: 성장주, 배당주, 해외주식"
        onkeydown="if(event.key==='Enter') createPortfolio()">
    </div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeNewPortfolioModal()">취소</button>
      <button class="btn-save" onclick="createPortfolio()">만들기</button>
    </div>
  </div>
</div>

<!-- 포트폴리오 이름 변경 모달 -->
<div class="modal-overlay" id="rename-ptab-modal">
  <div class="modal-box">
    <div class="modal-title">이름 변경</div>
    <div class="form-group">
      <label class="form-label">새 이름</label>
      <input id="rename-ptab-name" class="form-input" type="text"
        onkeydown="if(event.key==='Enter') saveRename()">
    </div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeRenameModal()">취소</button>
      <button class="btn-save" onclick="saveRename()">저장</button>
    </div>
  </div>
</div>

<!-- 자금 기록 모달 -->
<div class="modal-overlay" id="cf-modal">
  <div class="modal-box">
    <div class="modal-title">자금 기록 추가</div>
    <div class="form-group">
      <label class="form-label">구분</label>
      <select id="cf-type" class="form-select">
        <option value="in">🟢 입금</option>
        <option value="out">🔴 출금</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">금액 (원)</label>
      <input id="cf-amount" class="form-input" type="number" placeholder="0" min="1" step="any">
    </div>
    <div class="form-group">
      <label class="form-label">메모 (선택)</label>
      <input id="cf-memo" class="form-input" type="text" placeholder="예: 초기 투자, 추가 매수">
    </div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeCashflowModal()">취소</button>
      <button class="btn-save" id="cf-btn-save" onclick="saveCashflow()">저장</button>
    </div>
  </div>
</div>

<script>
const PNAME = "{pname_js}";
const UID   = {uid};
const TOKEN = "{token}";
let _editMode = false, _editName = '';
let _renamePname = '';

function onCountryChange() {{
  const isCash = document.getElementById('f-country').value === '현금';
  document.getElementById('row-name').style.display    = isCash ? 'none' : '';
  document.getElementById('row-qty-avg').style.display = isCash ? 'none' : '';
  document.getElementById('row-cash').style.display    = isCash ? '' : 'none';
}}

function openAddModal() {{
  _editMode = false; _editName = '';
  document.getElementById('modal-title').textContent = '종목 추가';
  document.getElementById('f-name').value = '';
  document.getElementById('f-name').disabled = false;
  document.getElementById('f-country').value = 'KR';
  document.getElementById('f-qty').value = '';
  document.getElementById('f-avg').value = '';
  document.getElementById('f-cash').value = '';
  onCountryChange();
  document.getElementById('modal').classList.add('open');
}}

function openEditModal(d) {{
  _editMode = true; _editName = d.name;
  document.getElementById('modal-title').textContent = '종목 수정';
  document.getElementById('f-name').value = d.name;
  document.getElementById('f-name').disabled = true;
  document.getElementById('f-country').value = d.country;
  document.getElementById('f-qty').value = d.qty;
  document.getElementById('f-avg').value = d.avg;
  document.getElementById('f-cash').value = d.country === '현금' ? d.avg : '';
  onCountryChange();
  document.getElementById('modal').classList.add('open');
}}

function closeModal() {{ document.getElementById('modal').classList.remove('open'); }}

async function saveStock() {{
  const btn = document.getElementById('btn-save');
  btn.disabled = true; btn.textContent = '저장 중...';
  const isCash = document.getElementById('f-country').value === '현금';
  const payload = isCash ? {{
    종목명: '현금', 국가: '현금', 수량: 1,
    평단가: parseFloat(document.getElementById('f-cash').value) || 0,
  }} : {{
    종목명: document.getElementById('f-name').value.trim(),
    국가:   document.getElementById('f-country').value,
    수량:   parseFloat(document.getElementById('f-qty').value) || 0,
    평단가: parseFloat(document.getElementById('f-avg').value) || 0,
  }};
  if (!isCash && !payload.종목명) {{ alert('종목명을 입력하세요'); btn.disabled=false; btn.textContent='저장'; return; }}
  try {{
    const res = await fetch(`/u/${{UID}}/api/p/${{PNAME}}/stock?t=${{TOKEN}}`, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload),
    }});
    if (res.ok) {{ location.reload(); }}
    else {{ const e = await res.json(); alert('오류: ' + e.error); btn.disabled=false; btn.textContent='저장'; }}
  }} catch(e) {{ alert('네트워크 오류'); btn.disabled=false; btn.textContent='저장'; }}
}}

async function deleteStock(name) {{
  if (!confirm(`"${{name}}" 종목을 삭제할까요?`)) return;
  const res = await fetch(`/u/${{UID}}/api/p/${{PNAME}}/stock/${{encodeURIComponent(name)}}?t=${{TOKEN}}`, {{method:'DELETE'}});
  if (res.ok) {{ location.reload(); }}
  else {{ const e = await res.json(); alert('오류: ' + e.error); }}
}}

async function refreshPrices() {{
  const btn = document.getElementById('refresh-btn');
  if (!btn) return;
  btn.textContent = '조회 중...'; btn.disabled = true;
  try {{
    const ctrl = new AbortController();
    const tid  = setTimeout(() => ctrl.abort(), 120000);
    const res  = await fetch(`/u/${{UID}}/api/p/${{PNAME}}/refresh?t=${{TOKEN}}`, {{method:'POST', signal: ctrl.signal}});
    clearTimeout(tid);
    if (res.ok) {{ location.reload(); }}
    else {{ let msg = `HTTP ${{res.status}}`; try {{ const e = await res.json(); msg = e.error || msg; }} catch(_) {{}} alert('가격 조회 오류: ' + msg); }}
  }} catch(e) {{
    alert('가격 조회 오류: ' + (e.name === 'AbortError' ? '시간 초과 (120초)' : e.message));
  }} finally {{
    btn.textContent = '🔄 가격 새로고침'; btn.disabled = false;
  }}
}}

document.getElementById('modal').addEventListener('click', function(e) {{
  if (e.target === this) closeModal();
}});

function openNewPortfolioModal() {{
  document.getElementById('new-ptab-name').value = '';
  document.getElementById('new-ptab-modal').classList.add('open');
  setTimeout(() => document.getElementById('new-ptab-name').focus(), 50);
}}
function closeNewPortfolioModal() {{
  document.getElementById('new-ptab-modal').classList.remove('open');
}}
async function createPortfolio() {{
  const name = document.getElementById('new-ptab-name').value.trim();
  if (!name) {{ alert('이름을 입력하세요'); return; }}
  const res = await fetch(`/u/${{UID}}/api/portfolios?t=${{TOKEN}}`, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ name }}),
  }});
  if (res.ok) {{
    const d = await res.json();
    location.href = `/u/${{UID}}/p/${{d.pname}}?t=${{TOKEN}}`;
  }} else {{
    const e = await res.json(); alert('오류: ' + e.error);
  }}
}}

function openRenameModal(pname, currentName) {{
  _renamePname = pname;
  document.getElementById('rename-ptab-name').value = currentName;
  document.getElementById('rename-ptab-modal').classList.add('open');
  setTimeout(() => document.getElementById('rename-ptab-name').focus(), 50);
}}
function closeRenameModal() {{
  document.getElementById('rename-ptab-modal').classList.remove('open');
}}
async function saveRename() {{
  const name = document.getElementById('rename-ptab-name').value.trim();
  if (!name) {{ alert('이름을 입력하세요'); return; }}
  const res = await fetch(`/u/${{UID}}/api/portfolios/${{_renamePname}}?t=${{TOKEN}}`, {{
    method: 'PATCH',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ name }}),
  }});
  if (res.ok) {{ location.reload(); }}
  else {{ const e = await res.json(); alert('오류: ' + e.error); }}
}}

async function deletePortfolio(pname) {{
  if (!confirm('이 포트폴리오를 삭제할까요?\\n모든 데이터(종목, 자금기록, 히스토리)가 삭제됩니다.')) return;
  const res = await fetch(`/u/${{UID}}/api/portfolios/${{pname}}?t=${{TOKEN}}`, {{ method: 'DELETE' }});
  if (res.ok) {{
    const d = await res.json();
    location.href = d.redirect;
  }} else {{
    const e = await res.json(); alert('오류: ' + e.error);
  }}
}}

document.getElementById('new-ptab-modal').addEventListener('click', function(e) {{
  if (e.target === this) closeNewPortfolioModal();
}});
document.getElementById('rename-ptab-modal').addEventListener('click', function(e) {{
  if (e.target === this) closeRenameModal();
}});

function openCashflowModal() {{
  document.getElementById('cf-amount').value = '';
  document.getElementById('cf-memo').value   = '';
  document.getElementById('cf-type').value   = 'in';
  document.getElementById('cf-modal').classList.add('open');
}}
function closeCashflowModal() {{
  document.getElementById('cf-modal').classList.remove('open');
}}
async function saveCashflow() {{
  const btn    = document.getElementById('cf-btn-save');
  btn.disabled = true; btn.textContent = '저장 중...';
  const type   = document.getElementById('cf-type').value;
  const amount = parseFloat(document.getElementById('cf-amount').value);
  const memo   = document.getElementById('cf-memo').value.trim();
  if (!amount || amount <= 0) {{
    alert('금액을 입력하세요');
    btn.disabled = false; btn.textContent = '저장';
    return;
  }}
  try {{
    const res = await fetch(`/u/${{UID}}/api/cashflow/${{PNAME}}?t=${{TOKEN}}`, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ type, amount, memo }}),
    }});
    if (res.ok) {{ location.reload(); }}
    else {{
      const e = await res.json();
      alert('오류: ' + e.error);
      btn.disabled = false; btn.textContent = '저장';
    }}
  }} catch(e) {{
    alert('네트워크 오류');
    btn.disabled = false; btn.textContent = '저장';
  }}
}}
document.getElementById('cf-modal').addEventListener('click', function(e) {{
  if (e.target === this) closeCashflowModal();
}});

try {{
  Chart.defaults.font.family = "'Noto Sans KR',sans-serif";
  Chart.defaults.color = "#94a3b8";
  Chart.defaults.font.size = 11;

  const P = {wp};

  const donutCfg = (labels, data, colors) => ({{
    type: "doughnut",
    data: {{
      labels,
      datasets: [{{ data, backgroundColor: colors, borderWidth: 3, borderColor: "#fff", hoverOffset: 6 }}],
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      cutout: "65%",
      plugins: {{
        legend: {{ position: "bottom", labels: {{ boxWidth: 9, padding: 12, font: {{ size: 11 }}, color: "#64748b" }} }},
        tooltip: {{ callbacks: {{ label: c => ` ${{c.label}}: ${{c.parsed}}%` }} }},
      }},
    }},
  }});

  new Chart(document.getElementById("weightChart"),  donutCfg({wl}, {wd}, P));
  new Chart(document.getElementById("countryChart"), donutCfg({cl}, {cd}, {country_colors}));

  new Chart(document.getElementById("returnChart"), {{
    type: "bar",
    data: {{
      labels: {rl},
      datasets: [{{ label: "수익률(%)", data: {rd}, backgroundColor: {rc}, borderRadius: 4, borderSkipped: false }}],
    }},
    options: {{
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: c => ` ${{c.parsed.x >= 0 ? "+" : ""}}${{c.parsed.x.toFixed(2)}}%` }} }},
      }},
      scales: {{
        x: {{ grid: {{ color: "#f1f5f9" }}, ticks: {{ color: "#94a3b8", callback: v => (v >= 0 ? "+" : "") + v + "%" }} }},
        y: {{ grid: {{ display: false }}, ticks: {{ color: "#64748b", font: {{ size: 11 }} }} }},
      }},
    }},
  }});

  {hist_chart_js}
}} catch(e) {{
  console.error("Chart 초기화 오류:", e);
}}
</script>
</body>
</html>"""


def build_html(df: pd.DataFrame) -> str:
    return build_user_html(df)

# =======================================================
# bot.py
# =======================================================
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

# ══════════════════════════════════════════
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "여기에_텔레그램_토큰_입력")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
NGROK_TOKEN      = os.getenv("NGROK_TOKEN",       "여기에_ngrok_토큰_입력")
FLASK_PORT       = int(os.getenv("FLASK_PORT",    "5050"))
# USE_NGROK=false → ngrok 없이 Flask 직접 노출 (GCP 등 공인 IP 서버에서 사용)
# FLASK_PUBLIC_URL → 외부에서 접근 가능한 URL (예: http://34.xx.xx.xx:5050)
USE_NGROK        = os.getenv("USE_NGROK", "true").lower() not in ("false", "0", "no")
FLASK_PUBLIC_URL = os.getenv("FLASK_PUBLIC_URL", "")
KST              = pytz.timezone("Asia/Seoul")
# ══════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S", level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── 전역 상태 ──
# all_users[uid] = {"portfolios": {pname: {...}}, "active_pname": ""}
all_users:   dict      = {}
_users_lock: threading.Lock = threading.Lock()
public_url:  str       = ""
tg_bot:      Bot | None = None

# ── 대시보드 빌드 중복 방지 ──
_build_lock  = threading.Lock()   # _building / _hist_check 접근용
_building:   set  = set()         # (uid, pname) 튜플
_hist_check: dict = {}            # (uid, pname) -> "YYYY-MM-DD"

app_flask    = Flask(__name__)
REQUIRED_COLS = {"종목명", "국가", "평단가", "수량", "통화"}


@app_flask.errorhandler(400)
@app_flask.errorhandler(403)
@app_flask.errorhandler(404)
@app_flask.errorhandler(500)
def _json_error(e):
    return jsonify({"error": str(e)}), e.code


def _get_user_state(uid: int) -> dict:
    """uid의 상태 반환. 없으면 디스크에서 로드 (double-checked locking)."""
    if uid not in all_users:
        with _users_lock:
            if uid not in all_users:
                portfolios, active_pname = load_portfolios(uid)
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
    state["active_pname"] = pname
    save_portfolios(uid, state["portfolios"], pname)
    p     = state["portfolios"][pname]
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
    )


# ── 포트폴리오 관리 ──
@app_flask.route("/u/<int:uid>/api/portfolios", methods=["POST"])
def api_create_portfolio(uid: int):
    _check_token(uid)
    state = _get_user_state(uid)
    data  = request.get_json()
    name  = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "이름을 입력하세요"}), 400
    pname = create_portfolio(uid, name)
    state["portfolios"][pname] = {
        "name":        name,
        "last_update": None,
        "df":          pd.DataFrame(columns=["종목명", "국가", "비중(%)", "평단가", "수량", "통화"]),
    }
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
    state["portfolios"][pname]["name"] = name
    rename_portfolio(uid, pname, name)
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
    del portfolios[pname]
    new_active = delete_portfolio(uid, pname)
    if not new_active or new_active not in portfolios:
        new_active = next(iter(portfolios))
    state["active_pname"] = new_active
    token = get_user_token(uid)
    return jsonify({"ok": True, "redirect": f"/u/{uid}/p/{new_active}?t={token}"})


# ── 종목 추가/수정 ──
@app_flask.route("/u/<int:uid>/api/p/<pname>/stock", methods=["POST"])
def api_add_stock(uid: int, pname: str):
    _check_token(uid)
    state = _get_user_state(uid)
    if pname not in state["portfolios"]:
        state["portfolios"][pname] = {
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

        df = state["portfolios"][pname]["df"].copy()
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
        state["portfolios"][pname]["df"] = df.drop(columns=drop_cols)
        save_portfolios(uid, state["portfolios"], state["active_pname"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── 종목 삭제 ──
@app_flask.route("/u/<int:uid>/api/p/<pname>/stock/<path:name>", methods=["DELETE"])
def api_del_stock(uid: int, pname: str, name: str):
    _check_token(uid)
    state = _get_user_state(uid)
    if pname not in state["portfolios"]:
        return jsonify({"error": "포트폴리오 없음"}), 404
    df = state["portfolios"][pname]["df"]
    if name not in df["종목명"].values:
        return jsonify({"error": "종목 없음"}), 404
    state["portfolios"][pname]["df"] = df[df["종목명"] != name].reset_index(drop=True)
    save_portfolios(uid, state["portfolios"], state["active_pname"])
    return jsonify({"ok": True})


# ── 가격 재조회 ──
@app_flask.route("/u/<int:uid>/api/p/<pname>/refresh", methods=["POST"])
def api_refresh(uid: int, pname: str):
    _check_token(uid)
    state = _get_user_state(uid)
    if pname not in state["portfolios"]:
        return jsonify({"error": "포트폴리오 없음"}), 404
    df = state["portfolios"][pname].get("df")
    if df is None or len(df) == 0:
        return jsonify({"error": "종목을 먼저 추가해 주세요"}), 400
    try:
        build_dashboard_for(uid, pname)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 자금 기록 ──
@app_flask.route("/u/<int:uid>/api/cashflow/<pname>", methods=["GET"])
def api_get_cashflow(uid: int, pname: str):
    _check_token(uid)
    return jsonify(load_cashflow(uid, pname))


@app_flask.route("/u/<int:uid>/api/cashflow/<pname>", methods=["POST"])
def api_add_cashflow_route(uid: int, pname: str):
    _check_token(uid)
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
            tunnel     = ngrok.connect(FLASK_PORT, "http")
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
def build_dashboard_for(uid: int, pname: str) -> pd.DataFrame:
    state  = _get_user_state(uid)
    p      = state["portfolios"][pname]
    df_raw = p["df"].drop(
        columns=[c for c in ["현재가", "수익률(%)", "등락률(%)", "USD_KRW"] if c in p["df"].columns]
    )
    df = fetch_prices(df_raw)
    state["portfolios"][pname]["df"]          = df
    state["portfolios"][pname]["last_update"] = datetime.now(KST)
    usd_krw = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns and len(df) > 0 else 1370.0
    save_snapshot(uid, pname, df, usd_krw)
    save_portfolios(uid, state["portfolios"], state["active_pname"])
    return df


def _build_dashboard_bg(uid: int, pname: str) -> None:
    """백그라운드 스레드용 wrapper — 완료 후 _building에서 제거."""
    try:
        build_dashboard_for(uid, pname)
    finally:
        with _build_lock:
            _building.discard((uid, pname))


def _trigger_build_if_needed(uid: int, pname: str) -> None:
    """오늘 아직 빌드하지 않았고, 현재 빌드 중이 아닐 때만 스레드 1개 생성."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    key   = (uid, pname)
    with _build_lock:
        if _hist_check.get(key) == today or key in _building:
            return
        _building.add(key)
        _hist_check[key] = today  # 스레드 시작 전에 기록 (중복 방지)
    threading.Thread(target=_build_dashboard_bg, args=(uid, pname), daemon=True).start()


# ────────────────────────────────────────
# 텍스트 요약
# ────────────────────────────────────────
def _summary_text(uid: int, pname: str) -> str:
    state = _get_user_state(uid)
    p     = state["portfolios"][pname]
    df    = p["df"]
    ts    = p["last_update"].strftime("%m/%d %H:%M") if p.get("last_update") else "—"
    name  = p.get("name", "포트폴리오")
    token = get_user_token(uid)
    url   = f"{public_url}/u/{uid}/p/{pname}?t={token}"

    lines = [f"📊 *{name} 요약* `{ts} KST`\n"]
    usd_krw_s = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns and len(df) > 0 else 1370.0
    valid = df[df["수익률(%)"].notna() & (df["국가"] != "현금")]
    if not valid.empty:
        buy_w = valid.apply(
            lambda r: float(r["평단가"]) * (float(r["수량"]) if pd.notna(r.get("수량")) else 0.0)
                      * (usd_krw_s if str(r.get("통화", "KRW")).upper() == "USD" else 1.0), axis=1
        )
        total = (valid["수익률(%)"] * buy_w).sum() / buy_w.sum() if buy_w.sum() > 0 else 0.0
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
    url = f"{public_url}/u/{uid}/p/{active}?t={token}" if active else public_url
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
        url  = f"{public_url}/u/{uid}/p/{pname}?t={token}"
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
    msg = await update.message.reply_text("🔄 가격 재조회 중...")
    try:
        await asyncio.get_running_loop().run_in_executor(None, build_dashboard_for, uid, active_pname)
        ts    = state["portfolios"][active_pname]["last_update"].strftime("%m/%d %H:%M")
        token = get_user_token(uid)
        url   = f"{public_url}/u/{uid}/p/{active_pname}?t={token}"
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
                await asyncio.get_running_loop().run_in_executor(
                    None, build_dashboard_for, uid, pname
                )
                text = f"⏰ *{label} 자동 업데이트*\n\n{_summary_text(uid, pname)}"
                await tg_bot.send_message(
                    chat_id=uid,
                    text=text,
                    parse_mode=None,
                    disable_web_page_preview=True,
                )
                log.info(f"  → uid={uid} {p.get('name')} ({pname}) 전송 완료")
            except Exception as e:
                log.error(f"  → uid={uid} {pname} 전송 실패: {e}")


async def scheduled_snapshot():
    """가격 재조회 없이 현재 df 기준으로 모든 유저·포트폴리오 스냅샷 저장."""
    for uid, state in list(all_users.items()):
        for pname, p in list(state["portfolios"].items()):
            df = p.get("df")
            if df is None or len(df) == 0:
                continue
            try:
                usd_krw = float(df["USD_KRW"].iloc[0]) if "USD_KRW" in df.columns else 1370.0
                save_snapshot(uid, pname, df, usd_krw)
                log.info(f"  📸 자정 스냅샷: uid={uid} {p.get('name', pname)}")
            except Exception as e:
                log.error(f"  ⚠️  자정 스냅샷 실패 uid={uid} {pname}: {e}")


# ────────────────────────────────────────
# MAIN
# ────────────────────────────────────────
def main():
    global tg_bot, public_url

    log.info("=" * 55)
    log.info("  📊  포트폴리오 봇 시작 (멀티유저)")
    log.info("=" * 55)

    if TELEGRAM_CHAT_ID:
        state = _get_user_state(TELEGRAM_CHAT_ID)
        log.info(f"  📁 기본 유저 포트폴리오 {len(state['portfolios'])}개 로드")

    threading.Thread(target=run_flask, daemon=True).start()
    log.info(f"  🖥️  Flask 서버 시작 (port {FLASK_PORT})")

    if USE_NGROK:
        start_ngrok()
    elif FLASK_PUBLIC_URL:
        public_url = FLASK_PUBLIC_URL.rstrip("/")
        log.info(f"  🌐 공인 IP 모드: {public_url}")
    else:
        log.warning("  ⚠️  USE_NGROK=false이지만 FLASK_PUBLIC_URL 미설정 — 대시보드 링크가 비어 있습니다")

    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    tg_bot = tg_app.bot
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
