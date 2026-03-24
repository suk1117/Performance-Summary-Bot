"""
_hist_check 버그 수정 테스트 (test_hist_check)
  1. _build_dashboard_bg 성공 시 _hist_check 제거 → 당일 재접속에도 빌드 트리거 가능
  2. _build_dashboard_bg 실패 시 _hist_check 제거 → 재시도 가능
  3. scheduled_send else 블록에 _hist_check 설정 코드 없음
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import inspect
import threading
import asyncio
import pandas as pd
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock

import combined_bot
from combined_bot import (
    _build_dashboard_bg, _trigger_build_if_needed,
    _build_lock, _building, _hist_check,
    _get_user_state, load_portfolios, all_users,
    scheduled_send, KST,
    DATA_DIR,
)

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name, cond):
    tag = PASS if cond else FAIL
    results.append((tag, name))
    print(f"  {tag}  {name}")

BASE_UID = 99990000

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
print(" 1. _build_dashboard_bg 성공 시 _hist_check 제거")
print("="*60)

UID = BASE_UID + 1
PNAME = "p1"
KEY = (UID, PNAME)
TODAY = datetime.now(KST).strftime("%Y-%m-%d")

# 사전 조건: _hist_check와 _building에 키 등록 (trigger가 하는 것처럼)
with _build_lock:
    _building.add(KEY)
    _hist_check[KEY] = TODAY

with patch.object(combined_bot, "build_dashboard_for", return_value=None):
    _build_dashboard_bg(UID, PNAME)

with _build_lock:
    hist_cleared   = KEY not in _hist_check
    building_clear = KEY not in _building

check("빌드 성공 후 _hist_check에서 키 제거됨", hist_cleared)
check("빌드 성공 후 _building에서 키 제거됨",   building_clear)

# 후속: _trigger_build_if_needed가 스킵하지 않고 스레드 기동하는지 확인
# (실제 빌드는 mock으로 차단)
triggered = []

def _fake_bg(uid, pname):
    triggered.append((uid, pname))

with patch.object(combined_bot, "_build_dashboard_bg", side_effect=_fake_bg):
    _trigger_build_if_needed(UID, PNAME)
    # 스레드가 시작되므로 잠시 대기
    import time; time.sleep(0.1)

check("_hist_check 제거 후 재접속 시 빌드 트리거 실행됨", len(triggered) > 0)

# 정리
with _build_lock:
    _building.discard(KEY)
    _hist_check.pop(KEY, None)


# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 2. _build_dashboard_bg 실패(예외) 시 _hist_check 제거")
print("="*60)

KEY2 = (UID, "p2")
with _build_lock:
    _building.add(KEY2)
    _hist_check[KEY2] = TODAY

def _raise(*a, **kw):
    raise RuntimeError("fake error")

with patch.object(combined_bot, "build_dashboard_for", side_effect=_raise):
    _build_dashboard_bg(UID, "p2")

with _build_lock:
    hist_cleared2   = KEY2 not in _hist_check
    building_clear2 = KEY2 not in _building

check("빌드 실패 후 _hist_check에서 키 제거됨", hist_cleared2)
check("빌드 실패 후 _building에서 키 제거됨",   building_clear2)

# 정리
with _build_lock:
    _building.discard(KEY2)
    _hist_check.pop(KEY2, None)


# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 3. scheduled_send else 블록에 _hist_check 설정 코드 없음")
print("="*60)

src_ss = inspect.getsource(scheduled_send)

# else 블록 이후 구간에서 _hist_check 할당 없음 확인
# "else:" 이후 텍스트에서 "_hist_check[" 패턴 탐색
else_idx = src_ss.find("else:\n")
# scheduled_send 내 else 블록 이후에 _hist_check[(uid, pname)] = 가 없는지 확인
hist_assign_after_else = "_hist_check[(uid, pname)] =" in src_ss[else_idx:]

check("scheduled_send else 블록에 _hist_check 재설정 코드 없음",
      not hist_assign_after_else)

# 소스 전체에서도 scheduled_send 안에 _hist_check 직접 할당 없음
hist_assign_in_ss = "_hist_check[" in src_ss
check("scheduled_send 내부에 _hist_check 직접 할당 없음",
      not hist_assign_in_ss)


# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 4. scheduled_send 실행 후 _hist_check에 키 잔존하지 않음 (런타임)")
print("="*60)

UID2 = BASE_UID + 2
import shutil
d = os.path.join(DATA_DIR, f"user_{UID2}")
if os.path.exists(d):
    shutil.rmtree(d, ignore_errors=True)

load_portfolios(UID2)
state2 = _get_user_state(UID2)
state2["portfolios"]["p1"]["df"] = _make_df()
state2["portfolios"]["p1"]["last_update"] = datetime.now()

KEY3 = (UID2, "p1")
# _hist_check 초기 상태 확인
with _build_lock:
    _hist_check.pop(KEY3, None)

async def _run_scheduled():
    real_loop = asyncio.get_running_loop()
    _orig_rie = real_loop.run_in_executor
    async def _noop(executor, fn, *args):
        return None
    real_loop.run_in_executor = _noop
    try:
        combined_bot.all_users[UID2] = state2
        with patch.object(combined_bot, "tg_bot") as mock_tg:
            mock_tg.send_message = AsyncMock(return_value=None)
            with patch.object(combined_bot, "_summary_text", return_value="요약"):
                await scheduled_send("테스트")
    finally:
        real_loop.run_in_executor = _orig_rie
        combined_bot.all_users.pop(UID2, None)

asyncio.run(_run_scheduled())

with _build_lock:
    no_hist = KEY3 not in _hist_check

check("scheduled_send 실행 후 _hist_check에 키 없음", no_hist)

if os.path.exists(d):
    shutil.rmtree(d, ignore_errors=True)


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
