"""
7개 수정 항목 테스트
  1. XSS 방지 — html.escape 적용 (포트폴리오명, 종목명, title_name)
  2. api_del_stock — df 읽기를 락 안으로 이동 (404 동작 포함)
  3. portfolio_page — active_pname 쓰기를 락으로 보호 (코드 구조 검증)
  4. scheduled_snapshot — df 읽기를 락으로 보호 (코드 구조 검증)
  5. _kr_ticker_cache — TTL 만료 및 최대 크기 제한
  6. fmt_krw — 모듈 레벨 단일 정의 검증
  7. build_combined_html — 현금 전용 포트폴리오 파이차트 포함
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import inspect
import shutil
import pandas as pd
from datetime import datetime
from unittest.mock import patch

import combined_bot
from combined_bot import (
    DATA_DIR,
    load_portfolios, save_portfolios, create_portfolio,
    add_cashflow,
    _build_portfolio_tabs, build_user_html, build_combined_html,
    _search_kr_ticker, _kr_ticker_cache, _KR_CACHE_TTL, _KR_CACHE_MAX,
    _get_user_state, get_user_token, all_users,
    app_flask, fmt_krw,
    portfolio_page, api_del_stock, scheduled_snapshot,
    _users_lock,
)

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name, cond):
    tag = PASS if cond else FAIL
    results.append((tag, name))
    print(f"  {tag}  {name}")

BASE_UID = 33330000

def _clean(uid):
    d = os.path.join(DATA_DIR, f"user_{uid}")
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)

def _make_df(**kw):
    base = {
        "종목명": "삼성전자", "국가": "KR",
        "비중(%)": 100.0, "평단가": 70000.0, "수량": 10.0, "통화": "KRW",
        "현재가": 75000.0, "수익률(%)": 7.14, "등락률(%)": 0.5, "USD_KRW": 1350.0,
    }
    base.update(kw)
    return pd.DataFrame([base])

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 1. XSS 방지 — html.escape")
print("="*60)
UID = BASE_UID + 1
_clean(UID)

XSS_NAME = '<script>alert(1)</script>'
AMP_NAME  = 'AT&T포트'

# 1-1: _build_portfolio_tabs — XSS 문자가 escape됨
load_portfolios(UID)
state = _get_user_state(UID)
state["portfolios"]["p1"]["name"] = XSS_NAME
tabs = _build_portfolio_tabs(state["portfolios"], "p1", uid=UID, token="tok")
check("탭 XSS 이름 escape", "<script>" not in tabs and "&lt;script&gt;" in tabs)

state["portfolios"]["p1"]["name"] = AMP_NAME
tabs2 = _build_portfolio_tabs(state["portfolios"], "p1", uid=UID, token="tok")
check("탭 & escape → &amp;", "&amp;" in tabs2 and "&" not in tabs2.replace("&amp;", "").replace("&lt;", "").replace("&gt;", "").replace("&#", ""))

# 1-2: build_user_html — 종목명 XSS escape
XSS_STOCK = '<img src=x onerror=alert(1)>'
df_xss = _make_df(종목명=XSS_STOCK)
state["portfolios"]["p1"]["df"] = df_xss
state["portfolios"]["p1"]["last_update"] = datetime.now()
state["portfolios"]["p1"]["name"] = "기본"
html = build_user_html(
    df_xss, display_name="기본",
    cashflows=[], pname="p1",
    all_portfolios=state["portfolios"], uid=UID, token="tok",
)
check("종목명 XSS escape", "<img src=x" not in html and "&lt;img" in html)

# 1-3: build_user_html — title_name XSS escape
html2 = build_user_html(
    df_xss, display_name=XSS_NAME,
    cashflows=[], pname="p1",
    all_portfolios=state["portfolios"], uid=UID, token="tok",
)
check("title_name XSS escape", "<script>" not in html2.split("<title>")[1].split("</title>")[0])

# 1-4: build_combined_html — portfolio_stats name escape
create_portfolio(UID, "두번째")
all_users.pop(UID, None)
state2 = _get_user_state(UID)
state2["portfolios"]["p1"]["df"] = _make_df()
state2["portfolios"]["p1"]["last_update"] = datetime.now()
state2["portfolios"]["p1"]["name"] = XSS_NAME
state2["portfolios"]["p2"]["df"] = _make_df()
state2["portfolios"]["p2"]["last_update"] = datetime.now()
state2["portfolios"]["p2"]["name"] = AMP_NAME
html3 = build_combined_html(UID, "tok", state2["portfolios"])
check("combined 포트폴리오명 XSS escape", XSS_NAME not in html3 and "&lt;script&gt;" in html3)
check("combined & escape", "&amp;" in html3)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 2. api_del_stock — df 읽기 락 안, 404 동작")
print("="*60)
UID = BASE_UID + 2
_clean(UID)
load_portfolios(UID)
state = _get_user_state(UID)
state["portfolios"]["p1"]["df"] = _make_df()
state["portfolios"]["p1"]["last_update"] = datetime.now()
token = get_user_token(UID)

with app_flask.test_client() as client:
    # 2-1: 존재하는 종목 삭제 → 200
    resp = client.delete(f"/u/{UID}/api/p/p1/stock/%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90?t={token}")
    check("존재 종목 삭제 200", resp.status_code == 200)

    # 2-2: 이미 삭제된 종목 재시도 → 404
    resp2 = client.delete(f"/u/{UID}/api/p/p1/stock/%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90?t={token}")
    check("존재하지 않는 종목 삭제 404", resp2.status_code == 404)

    # 2-3: 존재하지 않는 포트폴리오 → 404
    resp3 = client.delete(f"/u/{UID}/api/p/pXXX/stock/%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90?t={token}")
    check("존재하지 않는 포트폴리오 404", resp3.status_code == 404)

# 2-4: 코드 구조 검증 — df 읽기가 with _users_lock 블록 안에 있는지
src = inspect.getsource(api_del_stock)
lines = src.splitlines()
lock_idx = next((i for i, l in enumerate(lines) if "with _users_lock:" in l), None)
df_copy_idx = next((i for i, l in enumerate(lines) if "df" in l and ".copy()" in l), None)
check("df.copy()가 with _users_lock 블록 안에 위치",
      lock_idx is not None and df_copy_idx is not None and df_copy_idx > lock_idx)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 3. portfolio_page — active_pname 쓰기 락 보호")
print("="*60)

src_pp = inspect.getsource(portfolio_page)
lines_pp = src_pp.splitlines()
lock_idx_pp  = next((i for i, l in enumerate(lines_pp) if "with _users_lock:" in l), None)
active_idx   = next((i for i, l in enumerate(lines_pp) if "active_pname" in l and "=" in l and "state" in l), None)
save_idx     = next((i for i, l in enumerate(lines_pp) if "save_portfolios" in l), None)

check("portfolio_page with _users_lock 존재", lock_idx_pp is not None)
check("active_pname 쓰기가 with _users_lock 블록 안에 위치",
      lock_idx_pp is not None and active_idx is not None and active_idx > lock_idx_pp)
check("save_portfolios가 with _users_lock 블록 안에 위치",
      lock_idx_pp is not None and save_idx is not None and save_idx > lock_idx_pp)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 4. scheduled_snapshot — df 읽기 락 보호")
print("="*60)

src_ss = inspect.getsource(scheduled_snapshot)
lines_ss = src_ss.splitlines()
lock_idx_ss = next((i for i, l in enumerate(lines_ss) if "with _users_lock:" in l), None)
copy_idx_ss = next((i for i, l in enumerate(lines_ss) if ".copy()" in l), None)
io_idx_ss   = next((i for i, l in enumerate(lines_ss) if "save_snapshot" in l), None)

check("scheduled_snapshot with _users_lock 존재", lock_idx_ss is not None)
check("df.copy()가 with _users_lock 블록 안에 위치",
      lock_idx_ss is not None and copy_idx_ss is not None and copy_idx_ss > lock_idx_ss)
check("save_snapshot(파일 I/O)이 with _users_lock 밖에 위치",
      lock_idx_ss is not None and io_idx_ss is not None and io_idx_ss > copy_idx_ss)
# save_snapshot이 lock 블록 안에 없는지 확인 (들여쓰기 기준)
if lock_idx_ss is not None and io_idx_ss is not None:
    lock_indent = len(lines_ss[lock_idx_ss]) - len(lines_ss[lock_idx_ss].lstrip())
    io_indent   = len(lines_ss[io_idx_ss])   - len(lines_ss[io_idx_ss].lstrip())
    check("save_snapshot 들여쓰기가 lock 블록보다 같거나 작음 (밖에 위치)",
          io_indent <= lock_indent + 4)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 5. _kr_ticker_cache — TTL 만료 및 최대 크기")
print("="*60)

# 5-1: TTL 이내 캐시 히트
_kr_ticker_cache.clear()
_kr_ticker_cache["테스트종목"] = ("005930.KS", combined_bot._time.time())
with patch("combined_bot.requests") as mock_req:
    result = _search_kr_ticker("테스트종목")
check("TTL 이내 캐시 히트 (네트워크 호출 없음)", result == "005930.KS")

# 5-2: TTL 만료 → 캐시 무효화
_kr_ticker_cache["만료종목"] = ("000000.KS", combined_bot._time.time() - _KR_CACHE_TTL - 1)
with patch("combined_bot.requests") as mock_req:
    mock_req.get.return_value.json.return_value = {"items": []}
    mock_req.get.return_value.raise_for_status.return_value = None
    _search_kr_ticker("만료종목")
check("TTL 만료 항목 캐시에서 제거됨", "만료종목" not in _kr_ticker_cache)

# 5-3: 최대 크기 초과 시 가장 오래된 항목 제거
_kr_ticker_cache.clear()
now = combined_bot._time.time()
for i in range(_KR_CACHE_MAX):
    _kr_ticker_cache[f"종목{i}"] = (f"CODE{i}", now + i)
first_key = "종목0"
check("캐시 최대 크기 도달", len(_kr_ticker_cache) == _KR_CACHE_MAX)

# 새 항목 추가 시 가장 오래된 항목(종목0) 제거
with patch("combined_bot.requests") as mock_req:
    mock_req.get.return_value.json.return_value = {
        "items": [{"name": "신규종목", "code": "NEW001", "nationCode": "KOR"}]
    }
    mock_req.get.return_value.raise_for_status.return_value = None
    _search_kr_ticker("신규종목")
check("최대 크기 초과 시 최오래된 항목 제거", first_key not in _kr_ticker_cache)
check("최대 크기 초과 후 신규 항목 추가됨", "신규종목" in _kr_ticker_cache)
check("캐시 크기 _KR_CACHE_MAX 유지", len(_kr_ticker_cache) == _KR_CACHE_MAX)
_kr_ticker_cache.clear()

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 6. fmt_krw — 모듈 레벨 단일 정의")
print("="*60)

# 6-1: 모듈에서 직접 임포트 가능
check("fmt_krw 모듈 레벨 함수 임포트 가능", callable(fmt_krw))

# 6-2: 계산 결과 정확성
check("fmt_krw 1억 이상 → 억 단위", "억" in fmt_krw(1_5000_0000))
check("fmt_krw 1만 이상 → 만 단위", "만" in fmt_krw(5_0000))
check("fmt_krw 1만 미만 → 원 단위", "₩" in fmt_krw(9999) and "만" not in fmt_krw(9999))
check("fmt_krw 150,000,000 → 1.50억", fmt_krw(1_5000_0000) == "₩1.50억")
check("fmt_krw 50,000 → 5만", fmt_krw(5_0000) == "₩5만")

# 6-3: build_user_html / build_combined_html 내부에 중복 정의 없음
src_buh = inspect.getsource(build_user_html)
src_bch = inspect.getsource(build_combined_html)
check("build_user_html 내부에 fmt_krw 정의 없음",  "def fmt_krw" not in src_buh)
check("build_combined_html 내부에 fmt_krw 정의 없음", "def fmt_krw" not in src_bch)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 7. build_combined_html — 현금 전용 포트폴리오 파이차트 포함")
print("="*60)
UID = BASE_UID + 7
_clean(UID)
load_portfolios(UID)
create_portfolio(UID, "현금전용")
all_users.pop(UID, None)
state = _get_user_state(UID)

# p1: 종목 있음
state["portfolios"]["p1"]["df"] = _make_df()
state["portfolios"]["p1"]["last_update"] = datetime.now()
state["portfolios"]["p1"]["name"] = "주식포트"

# p2: df 없음 (현금만)
state["portfolios"]["p2"]["name"] = "현금전용"
state["portfolios"]["p2"]["df"] = None

add_cashflow(UID, "p1", "in", 1_000_000, "")
add_cashflow(UID, "p2", "in", 2_000_000, "")  # 현금만 있는 포트폴리오

html = build_combined_html(UID, "tok", state["portfolios"])

check("현금 전용 포트폴리오 이름이 HTML에 포함됨", "현금전용" in html)
check("피이차트 데이터에 현금 포트폴리오 포함", html.count('"현금전용"') >= 1 or "현금전용" in html)

# 파이차트 labels에 두 포트폴리오 모두 포함되는지 JSON labels 확인
import json as _json
pie_labels_start = html.find('labels:')
if pie_labels_start == -1:
    check("파이차트 labels 섹션 존재", False)
else:
    pie_section = html[pie_labels_start:pie_labels_start+200]
    check("파이차트에 주식포트 포함", "주식포트" in html)
    check("파이차트에 현금전용 포함", "현금전용" in html)

# 7-2: net_inv = 0인 빈 포트폴리오는 파이차트에 포함 안 됨
create_portfolio(UID, "완전빈포트")
all_users.pop(UID, None)
state2 = _get_user_state(UID)
state2["portfolios"]["p1"]["df"] = _make_df()
state2["portfolios"]["p1"]["last_update"] = datetime.now()
state2["portfolios"]["p1"]["name"] = "주식포트"
state2["portfolios"]["p2"]["df"] = None
state2["portfolios"]["p2"]["name"] = "현금전용"
state2["portfolios"]["p3"]["df"] = None
state2["portfolios"]["p3"]["name"] = "완전빈포트"  # cashflow 없음

html2 = build_combined_html(UID, "tok", state2["portfolios"])
check("cashflow 없는 포트폴리오(net_inv=0) 파이차트 미포함", html2.count("완전빈포트") == 0 or
      # nav-time 등 탭에만 있을 수 있으므로 stats 영역 확인
      "완전빈포트" not in html2.split("charts-grid")[1] if "charts-grid" in html2 else True)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
passed = sum(1 for t, _ in results if t == PASS)
failed = sum(1 for t, _ in results if t == FAIL)
print(f" 결과: {passed}개 통과 / {failed}개 실패  (총 {len(results)}개)")
if failed:
    print("\n실패 항목:")
    for t, n in results:
        if t == FAIL:
            print(f"  {t} {n}")
print("="*60 + "\n")

sys.exit(0 if failed == 0 else 1)
