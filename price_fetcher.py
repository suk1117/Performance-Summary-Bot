"""
price_fetcher.py
현재가 조회 + 수익률 계산
  - KR 주식: 네이버 금융 (종목명 → 티커 검색 → 현재가)
  - US 주식: 네이버 금융 (AAPL:NASDAQ 형식)
  - 환율:    네이버 금융 (FX_USDKRW)
"""
from __future__ import annotations
import requests
import pandas as pd

# ── 공통 헤더 ──
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
}

# ── 캐시 ──
_kr_ticker_cache: dict[str, str] = {}       # 종목명 → 티커
_us_exchange_cache: dict[str, str] = {}     # 티커 → 거래소(NASDAQ/NYSE)


# ────────────────────────────────────────
# 1. KR 종목명 → 티커 검색
# ────────────────────────────────────────
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
        # 정확히 이름이 일치하는 종목 우선
        for item in items:
            if item.get("name") == name and item.get("nationCode") == "KOR":
                code = item["code"]
                _kr_ticker_cache[name] = code
                print(f"    🔎 {name} → {code}")
                return code
        # 없으면 첫 번째 KOR 종목
        for item in items:
            if item.get("nationCode") == "KOR":
                code = item["code"]
                _kr_ticker_cache[name] = code
                print(f"    🔎 {name} → {code} (첫 번째 결과)")
                return code
    except Exception as e:
        print(f"  ⚠️  티커 검색 실패 ({name}): {e}")
    return None


# ────────────────────────────────────────
# 2. 네이버 모바일 API로 현재가 조회
# ────────────────────────────────────────
def _naver_stock_price(code: str) -> float | None:
    """
    code 예시: "005930" (KR), "AAPL:NASDAQ" (US)
    """
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        r   = requests.get(url, headers=HEADERS, timeout=5)
        r.raise_for_status()
        data = r.json()
        # closePrice: 당일 종가 / currentPrice: 실시간
        price_str = (
            data.get("currentPrice")
            or data.get("closePrice")
            or data.get("stockEndPrice")
        )
        if price_str:
            return float(str(price_str).replace(",", ""))
    except Exception as e:
        print(f"  ⚠️  네이버 가격 조회 실패 ({code}): {e}")
    return None


# ────────────────────────────────────────
# 3. KR 주식 현재가
# ────────────────────────────────────────
def get_kr_price(name: str) -> float | None:
    ticker = _search_kr_ticker(name)
    if not ticker:
        return None
    return _naver_stock_price(ticker)


# ────────────────────────────────────────
# 4. US 주식 현재가 (네이버 금융)
# ────────────────────────────────────────
def get_us_price(ticker: str) -> float | None:
    """ticker = 'AAPL', 'TSLA' 등 심볼만 입력"""
    # 캐시에 거래소 정보 있으면 바로 사용
    if ticker in _us_exchange_cache:
        code  = f"{ticker}:{_us_exchange_cache[ticker]}"
        price = _naver_stock_price(code)
        if price:
            return price

    # 거래소 순서대로 시도
    for exchange in ["NASDAQ", "NYSE", "AMEX"]:
        code  = f"{ticker}:{exchange}"
        price = _naver_stock_price(code)
        if price:
            _us_exchange_cache[ticker] = exchange
            print(f"    🔎 {ticker} → {code}")
            return price

    # 네이버 실패 시 yfinance fallback
    try:
        import yfinance as yf
        t    = yf.Ticker(ticker)
        info = t.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if price is None:
            hist = t.history(period="2d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        if price:
            print(f"    ⚠️  {ticker}: yfinance fallback 사용")
            return price
    except Exception as e:
        print(f"  ⚠️  yfinance fallback 실패 ({ticker}): {e}")

    return None


# ────────────────────────────────────────
# 5. USD/KRW 환율
# ────────────────────────────────────────
def get_usd_krw() -> float:
    # yfinance 우선
    try:
        import yfinance as yf
        hist = yf.Ticker("USDKRW=X").history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except:
        pass

    # fallback: 네이버 금융
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
    except:
        pass

    return 1370.0


# ────────────────────────────────────────
# 6. 전체 포트폴리오 가격 조회
# ────────────────────────────────────────
def fetch_prices(df: pd.DataFrame) -> pd.DataFrame:
    usd_krw = get_usd_krw()
    print(f"  💱 USD/KRW: {usd_krw:,.1f}")

    current_prices, returns = [], []

    for _, row in df.iterrows():
        name    = str(row["종목명"]).strip()
        country = str(row["국가"]).strip()
        avg     = float(row["평단가"])

        # 현금
        if country == "현금":
            current_prices.append(avg)
            returns.append(0.0)
            continue

        print(f"  🔍 {name} ({country})")

        if country == "KR":
            price = get_kr_price(name)
        elif country == "US":
            price = get_us_price(name)   # 종목명이 곧 티커 (AAPL 등)
        else:
            price = None

        if price is None or avg == 0:
            current_prices.append(None)
            returns.append(None)
        else:
            current_prices.append(price)
            returns.append(round((price - avg) / avg * 100, 2))

    df = df.copy()
    df["현재가"]    = current_prices
    df["수익률(%)"] = returns
    df["USD_KRW"]   = usd_krw
    return df
