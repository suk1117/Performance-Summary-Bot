"""
price_fetcher.py
현재가 조회 + 수익률 계산 모듈
dashboard.py, bot.py 공통으로 사용
"""
from __future__ import annotations
import os
import ssl
import shutil
from datetime import date
import pandas as pd
import yfinance as yf

# ── Windows 한글 경로 SSL 오류 우회 ──────────────────────────────
# curl_cffi 가 한글 경로의 certifi 를 읽지 못하는 문제를
# yfinance 내부 세션의 verify=False 로 해결
ssl._create_default_https_context = ssl._create_unverified_context
try:
    from curl_cffi import requests as _cffi_req
    _orig_session_init = _cffi_req.Session.__init__
    def _patched_init(self, *a, **kw):
        kw.setdefault("verify", False)
        _orig_session_init(self, *a, **kw)
    _cffi_req.Session.__init__ = _patched_init
except Exception:
    pass
# ─────────────────────────────────────────────────────────────────


def get_kr_price(ticker: str) -> float | None:
    try:
        from pykrx import stock as pykrx_stock
        today = date.today().strftime("%Y%m%d")
        from_date = (pd.Timestamp.today() - pd.Timedelta(days=7)).strftime("%Y%m%d")
        df = pykrx_stock.get_market_ohlcv_by_date(
            fromdate=from_date, todate=today, ticker=ticker
        )
        if df.empty:
            return None
        return float(df["종가"].iloc[-1])
    except Exception as e:
        print(f"  [경고] pykrx {ticker}: {e}")
        return None


def get_us_price(ticker: str) -> float | None:
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if price is None:
            hist = t.history(period="2d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        return price
    except Exception as e:
        print(f"  [경고] yfinance {ticker}: {e}")
        return None


def get_usd_krw() -> float:
    try:
        hist = yf.Ticker("USDKRW=X").history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except:
        pass
    return 1370.0


def fetch_prices(df: pd.DataFrame) -> pd.DataFrame:
    """수익률 계산 후 데이터프레임 반환"""
    usd_krw = get_usd_krw()
    print(f"  USD/KRW: {usd_krw:,.1f}")

    current_prices, returns = [], []

    for _, row in df.iterrows():
        ticker  = str(row["티커"]).strip()
        country = str(row["국가"]).strip()
        avg     = float(row["평단가"])

        if country == "현금" or ticker.endswith("_CASH"):
            current_prices.append(avg)
            returns.append(0.0)
            continue

        print(f"  조회: {row['종목명']} ({ticker})")
        price = get_kr_price(ticker) if country == "KR" else get_us_price(ticker)

        if price is None or avg == 0:
            current_prices.append(None)
            returns.append(None)
        else:
            current_prices.append(price)
            returns.append(round((price - avg) / avg * 100, 2))

    df = df.copy()
    df["현재가"]   = current_prices
    df["수익률(%)"] = returns
    df["USD_KRW"]  = usd_krw
    return df
