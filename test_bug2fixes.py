"""
버그 수정 테스트 (test_bug2fixes)
  1. load_portfolios — _migrate(uid, uid) 호출 (TELEGRAM_CHAT_ID 미참조)
  2. cash_krw 계산 — net_investment - stock_eval_krw (total_buy 기준 아님)
     2-1. save_snapshot() 내 cash_krw
     2-2. build_user_html() 내 cash_krw
"""
import sys, os, shutil, inspect, json
from datetime import date
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
from datetime import datetime
from unittest.mock import patch

import combined_bot
from combined_bot import (
    DATA_DIR, load_portfolios, save_snapshot, build_user_html,
    _get_user_state, _save_snapshot_inner, _history_path,
    KST,
)

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name, cond):
    tag = PASS if cond else FAIL
    results.append((tag, name))
    print(f"  {tag}  {name}")

BASE_UID = 77770000

def _clean(uid):
    d = os.path.join(DATA_DIR, f"user_{uid}")
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)

def _make_df(avg=70000.0, cur=80000.0, qty=10.0):
    return pd.DataFrame([{
        "종목명": "삼성전자", "국가": "KR",
        "비중(%)": 100.0, "평단가": avg, "수량": qty, "통화": "KRW",
        "현재가": cur, "수익률(%)": 14.29, "등락률(%)": 1.0, "USD_KRW": 1350.0,
    }])


# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 1. load_portfolios — _migrate(uid, uid) 호출 확인")
print("="*60)

# 소스 검증
src_lp = inspect.getsource(load_portfolios)
check("load_portfolios 소스에 _migrate(uid, uid) 존재",
      "_migrate(uid, uid)" in src_lp)
check("load_portfolios 소스에 TELEGRAM_CHAT_ID 미참조",
      "TELEGRAM_CHAT_ID" not in src_lp)

# 런타임: _migrate가 (uid, uid)로 호출되는지 확인
UID = BASE_UID + 1
_clean(UID)
called_with = []
_orig_migrate = combined_bot._migrate
def _spy_migrate(uid, owner_uid):
    called_with.append((uid, owner_uid))
    return _orig_migrate(uid, owner_uid)

with patch.object(combined_bot, "_migrate", side_effect=_spy_migrate):
    load_portfolios(UID)

check("_migrate 호출 시 owner_uid == uid",
      len(called_with) > 0 and called_with[0] == (UID, UID))
_clean(UID)


# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 2-1. save_snapshot() cash_krw = net_investment - stock_eval_krw")
print("="*60)

# avg=70000, cur=80000, qty=10
# stock_eval_krw = 800,000  /  total_buy = 700,000  /  net_inv = 900,000
# 올바른 cash = 900,000 - 800,000 = 100,000  → total_assets = 900,000
# 잘못된 cash = 900,000 - 700,000 = 200,000  → total_assets = 1,000,000

src_ss = inspect.getsource(_save_snapshot_inner)
check("_save_snapshot_inner 소스에 net_investment - stock_eval_krw 사용",
      "net_investment - stock_eval_krw" in src_ss)
check("_save_snapshot_inner 소스에 net_investment - total_buy 미사용",
      "net_investment - total_buy" not in src_ss)

# 런타임: 실제 파일에 기록된 total_assets 확인
UID = BASE_UID + 2
_clean(UID)
load_portfolios(UID)
df = _make_df(avg=70000.0, cur=80000.0, qty=10.0)

with patch.object(combined_bot, "get_net_investment", return_value=900_000.0):
    with patch.object(combined_bot, "compute_nav_units", return_value=(1000.0, 1.0)):
        save_snapshot(UID, "p1", df, usd_krw=1350.0)

fpath = _history_path(UID, "p1")
today = date.today().isoformat()
saved_assets = None
if os.path.exists(fpath):
    with open(fpath, "r", encoding="utf-8") as f:
        h = json.load(f)
    saved_assets = h.get(today, {}).get("total_assets")

# stock_eval=800,000 + cash=100,000 = 900,000
check("save_snapshot total_assets = 900,000 (stock_eval 800,000 + cash 100,000)",
      saved_assets is not None and abs(saved_assets - 900_000.0) < 1.0)
check("save_snapshot total_assets != 1,000,000 (total_buy 기준 오류값 아님)",
      saved_assets is None or abs(saved_assets - 1_000_000.0) > 1.0)

_clean(UID)


# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 2-2. build_user_html() cash_krw = net_investment - stock_eval_krw")
print("="*60)

src_buh = inspect.getsource(build_user_html)
check("build_user_html 소스에 net_investment - stock_eval_krw 사용",
      "net_investment - stock_eval_krw" in src_buh)
check("build_user_html 소스에 net_investment - total_buy 미사용",
      "net_investment - total_buy" not in src_buh)

# 런타임: cash_krw=100,000이 HTML에 노출되는지 확인
UID = BASE_UID + 3
_clean(UID)
load_portfolios(UID)
state3 = _get_user_state(UID)
df3 = _make_df(avg=70000.0, cur=80000.0, qty=10.0)
state3["portfolios"]["p1"]["df"] = df3
state3["portfolios"]["p1"]["name"] = "테스트"
state3["portfolios"]["p1"]["last_update"] = datetime.now(KST)

with patch.object(combined_bot, "get_net_investment", return_value=900_000.0):
    html = build_user_html(
        df3, display_name="테스트", cashflows=[], pname="p1",
        all_portfolios=state3["portfolios"], uid=UID, token="tok",
    )

check("build_user_html show_cash=True → 현금 행 포함됨", "현금" in html)
check("build_user_html cash_krw=100,000원(₩10만) 표시됨", "10만" in html)

cash_section_start = html.find("💵 현금")
cash_section = html[cash_section_start:cash_section_start+500] if cash_section_start != -1 else ""
check("현금 행에 200,000(total_buy 기준 오류값) 미표시",
      "200,000" not in cash_section)

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
