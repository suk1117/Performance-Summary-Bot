from __future__ import annotations
import logging
import time as _time

import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

from portfolio_bot.config import HEADERS

log = logging.getLogger(__name__)

_kr_ticker_cache: dict[str, tuple[str, float]] = {}  # {name: (code, timestamp)}
_KR_CACHE_TTL  = 60 * 60 * 24   # 24시간
_KR_CACHE_MAX  = 500             # 최대 항목 수
_us_exchange_cache: dict[str, str] = {}


def _search_kr_ticker(name: str) -> str | None:
    if name in _kr_ticker_cache:
        code, ts = _kr_ticker_cache[name]
        if _time.time() - ts < _KR_CACHE_TTL:
            return code
        else:
            del _kr_ticker_cache[name]
    try:
        url = "https://ac.stock.naver.com/ac"
        params = {"q": name, "q_enc": "UTF-8", "target": "stock,index,marketindicator"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=5)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        def _cache_write(code: str) -> str:
            if len(_kr_ticker_cache) >= _KR_CACHE_MAX:
                _kr_ticker_cache.pop(next(iter(_kr_ticker_cache)))
            _kr_ticker_cache[name] = (code, _time.time())
            return code
        for item in items:
            if item.get("name") == name and item.get("nationCode") == "KOR":
                code = item["code"]
                log.info(f"티커 검색: {name} → {code}")
                return _cache_write(code)
        for item in items:
            if item.get("nationCode") == "KOR":
                code = item["code"]
                log.info(f"티커 검색: {name} → {code} (첫 번째 결과)")
                return _cache_write(code)
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
