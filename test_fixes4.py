"""
잔존 문제 4개 수정 테스트
  1. build_dashboard_for — df_raw 읽기를 락 안으로 이동
  2. portfolio_stats["name"] 이중 escape 수정
  3. build_html 미사용 함수 제거
  4. 루프 안 import json as _json 제거
"""
import sys, os, shutil, inspect
sys.path.insert(0, os.path.dirname(__file__))

import combined_bot
from combined_bot import (
    DATA_DIR, all_users, _get_user_state, load_portfolios,
    build_combined_html, _build_portfolio_tabs,
    add_cashflow, get_user_token,
    build_dashboard_for, build_user_html,
    _users_lock,
)
import pandas as pd
from datetime import datetime
from html import escape as html_escape

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name, cond):
    tag = PASS if cond else FAIL
    results.append((tag, name))
    print(f"  {tag}  {name}")

BASE_UID = 55550000

def _clean(uid):
    d = os.path.join(DATA_DIR, f"user_{uid}")
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)
    all_users.pop(uid, None)

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
print(" 1. build_dashboard_for — df_raw 읽기 락 보호")
print("="*60)

src = inspect.getsource(build_dashboard_for)
lines = src.splitlines()

# 첫 번째 with _users_lock 찾기
first_lock_idx = next((i for i, l in enumerate(lines) if "with _users_lock:" in l), None)
# df_raw 할당 라인
dfraw_idx = next((i for i, l in enumerate(lines) if "df_raw" in l and "=" in l and "drop" in l), None)
# .copy() 라인 — 멀티라인 체이닝이므로 df_raw와 다른 줄일 수 있음
copy_idx = next((i for i, l in enumerate(lines) if ".copy()" in l), None)
# fetch_prices 라인
fetch_idx = next((i for i, l in enumerate(lines) if "fetch_prices" in l), None)
# save_snapshot 라인
snapshot_idx = next((i for i, l in enumerate(lines) if "save_snapshot(" in l), None)
# 두 번째 with _users_lock (쓰기용)
all_lock_idxs = [i for i, l in enumerate(lines) if "with _users_lock:" in l]
write_lock_idx = next((i for i in all_lock_idxs if snapshot_idx is not None and i > snapshot_idx), None)

check("with _users_lock 블록 2개 존재 (읽기용 + 쓰기용)", len(all_lock_idxs) >= 2)
check("df_raw 읽기가 첫 번째 락 안에 위치",
      first_lock_idx is not None and dfraw_idx is not None and dfraw_idx > first_lock_idx)
check(".copy()가 첫 번째 락 안에 위치",
      first_lock_idx is not None and copy_idx is not None and copy_idx > first_lock_idx)
check("fetch_prices가 락 밖에 위치 (첫 번째 락 블록 이후)",
      first_lock_idx is not None and fetch_idx is not None and fetch_idx > first_lock_idx)
check("save_snapshot이 쓰기용 락 앞에 위치",
      snapshot_idx is not None and write_lock_idx is not None and snapshot_idx < write_lock_idx)

# fetch_prices가 첫 번째 락 블록 안에 없는지 들여쓰기 확인
# 락 밖이면 fetch_indent == lock_indent (함수 본문 레벨)
if first_lock_idx is not None and fetch_idx is not None:
    lock_indent  = len(lines[first_lock_idx]) - len(lines[first_lock_idx].lstrip())
    fetch_indent = len(lines[fetch_idx]) - len(lines[fetch_idx].lstrip())
    check("fetch_prices 들여쓰기가 첫 번째 락 블록 밖 (락과 같은 레벨)",
          fetch_indent == lock_indent)
    check("fetch_prices가 첫 번째 락 블록 완전히 밖에 위치",
          fetch_indent <= lock_indent)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 2. portfolio_stats name — 이중 escape 수정")
print("="*60)

src_bch = inspect.getsource(build_combined_html)
lines_bch = src_bch.splitlines()

# portfolio_stats.append 내부에서 escape 호출 없는지 확인
append_blocks = []
in_append = False
for l in lines_bch:
    if "portfolio_stats.append" in l:
        in_append = True
    if in_append:
        append_blocks.append(l)
        if l.strip() == "})":
            in_append = False

append_text = "\n".join(append_blocks)
check('portfolio_stats.append 내 escape() 호출 없음 (저장 시 escape 제거)',
      'escape(' not in append_text)

# 출력 시점(stat_rows, portfolio_cards)에 escape 적용 확인
stat_rows_line = next((l for l in lines_bch if 'stat_rows +=' in l or ("stat_rows" in l and "escape" in l)), None)
# stat_rows 구성 코드에서 escape 사용 확인
stat_section = "\n".join(lines_bch)
stat_idx = next((i for i, l in enumerate(lines_bch) if 'stat_rows = ""' in l), None)
card_idx  = next((i for i, l in enumerate(lines_bch) if 'portfolio_cards = ""' in l), None)

if stat_idx is not None and card_idx is not None:
    stat_block = "\n".join(lines_bch[stat_idx:card_idx])
    check('stat_rows 생성 시 escape() 적용', 'escape(ps["name"])' in stat_block)

if card_idx is not None:
    card_end = next((i for i, l in enumerate(lines_bch[card_idx:], card_idx) if 'hist_section' in l), len(lines_bch))
    card_block = "\n".join(lines_bch[card_idx:card_end])
    check('portfolio_cards 생성 시 escape() 적용', 'escape(ps["name"])' in card_block)

# pie_labels에도 escape 적용 확인
pie_line = next((l for l in lines_bch if 'pie_labels' in l and 'json.dumps' in l), None)
check('pie_labels에 escape() 적용', pie_line is not None and 'escape(' in pie_line)

# 실제 렌더링 테스트
UID = BASE_UID + 2
_clean(UID)
load_portfolios(UID)
from combined_bot import create_portfolio
create_portfolio(UID, "두번째")
all_users.pop(UID, None)
state = _get_user_state(UID)

XSS = '<script>xss()</script>'
AMP = 'A&B포트'

state["portfolios"]["p1"]["df"] = _make_df()
state["portfolios"]["p1"]["last_update"] = datetime.now()
state["portfolios"]["p1"]["name"] = XSS

state["portfolios"]["p2"]["df"] = _make_df(종목명="AAPL", 국가="US", 통화="USD")
state["portfolios"]["p2"]["last_update"] = datetime.now()
state["portfolios"]["p2"]["name"] = AMP

add_cashflow(UID, "p1", "in", 1_000_000, "")
add_cashflow(UID, "p2", "in", 2_000_000, "")

html = build_combined_html(UID, "tok", state["portfolios"])

check('XSS 포트폴리오명 raw 미포함 (stat_rows/cards)',
      XSS not in html)
check('XSS escaped 버전 포함 (&lt;script&gt;)',
      '&lt;script&gt;' in html)
check('& → &amp; 변환 확인',
      '&amp;' in html)
check('pie_labels에 XSS raw 미포함',
      XSS not in html.split('pie_labels')[1][:500] if 'pie_labels' in html else True)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 3. build_html 미사용 함수 제거")
print("="*60)

check("build_html 함수 존재하지 않음", not hasattr(combined_bot, "build_html"))

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 4. 루프 안 import json as _json 제거")
print("="*60)

src_buh = inspect.getsource(build_user_html)
check("build_user_html 내부에 'import json' 없음", "import json" not in src_buh)
check("build_user_html 내부에 '_json.dumps' 없음", "_json.dumps" not in src_buh)
check("build_user_html에서 json.dumps 직접 사용", "json.dumps" in src_buh)

# 실제 렌더링 확인 — json.dumps가 올바르게 동작하는지
UID = BASE_UID + 4
_clean(UID)
load_portfolios(UID)
state = _get_user_state(UID)
df_test = _make_df()
state["portfolios"]["p1"]["df"] = df_test
state["portfolios"]["p1"]["last_update"] = datetime.now()
html2 = build_user_html(
    df_test, display_name="테스트",
    cashflows=[], pname="p1",
    all_portfolios=state["portfolios"], uid=UID, token="tok",
)
check("build_user_html 렌더링 정상 (json.dumps 오류 없음)", "삼성전자" in html2)
check("edit 버튼 JSON 데이터 포함", "openEditModal" in html2)

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
