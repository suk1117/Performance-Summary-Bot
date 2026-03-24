"""
3가지 버그 수정 테스트 (test_fixes8)
  1. _migrate() — 신규 유저에게 기존 portfolios.json 복사 안 함
  2. scheduled_send() — Forbidden/BadRequest → WARNING, 그 외 → ERROR 분기
  3. build_user_html() topnav — 🔄 버튼 추가 / build_combined_html — 미포함
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import inspect
import json
import shutil
import asyncio
import logging
import pandas as pd
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import combined_bot
from combined_bot import (
    DATA_DIR,
    _migrate, _portfolios_file, _user_dir,
    load_portfolios, create_portfolio,
    build_user_html, build_combined_html,
    _get_user_state, all_users,
    scheduled_send,
)

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name, cond):
    tag = PASS if cond else FAIL
    results.append((tag, name))
    print(f"  {tag}  {name}")

BASE_UID = 88880000

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
print(" 1. _migrate() — 신규 유저에게 기존 portfolios.json 복사 안 함")
print("="*60)

UID = BASE_UID + 1
_clean(UID)

# 구버전 멀티 포트폴리오 파일 data/portfolios.json 생성
old_portfolios_path = os.path.join(DATA_DIR, "portfolios.json")
old_existed = os.path.exists(old_portfolios_path)
old_backup  = None
if old_existed:
    with open(old_portfolios_path, "r", encoding="utf-8") as f:
        old_backup = f.read()

fake_old = {
    "active": "p1", "next_id": 2,
    "items": {"p1": {"name": "기존유저포트", "last_update": None, "df": [
        {"종목명": "기존유저종목", "국가": "KR", "비중(%)": 100.0,
         "평단가": 50000.0, "수량": 5.0, "통화": "KRW"}
    ]}}
}
with open(old_portfolios_path, "w", encoding="utf-8") as f:
    json.dump(fake_old, f, ensure_ascii=False)

# 신규 uid로 _migrate 호출
os.makedirs(_user_dir(UID), exist_ok=True)
_migrate(UID)

dst = _portfolios_file(UID)
# 신규 유저 파일이 없어야 함 (복사 차단됨)
check("신규 유저 portfolios.json 미생성 (기존 데이터 복사 차단)", not os.path.exists(dst))

# 1-2: data/portfolios.json 자체는 삭제되지 않아야 함
check("data/portfolios.json 원본 유지 (삭제 안 됨)", os.path.exists(old_portfolios_path))

# 복원
if old_existed and old_backup:
    with open(old_portfolios_path, "w", encoding="utf-8") as f:
        f.write(old_backup)
elif not old_existed and os.path.exists(old_portfolios_path):
    os.remove(old_portfolios_path)

# 1-3: 소스 코드에 shutil.copy2(old_portfolios 관련 코드 없음 확인
src_migrate = inspect.getsource(_migrate)
check("_migrate 소스에 old_portfolios 복사 블록 없음",
      "old_portfolios" not in src_migrate)
check("_migrate 소스에 portfolio.json 단일 마이그레이션 유지",
      "portfolio.json" in src_migrate)

_clean(UID)


# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 2. scheduled_send() — Forbidden/BadRequest WARNING, 그 외 ERROR")
print("="*60)

# 2-1: 소스 코드 구조 검증 (TgForbidden/TgBadRequest 별칭 사용)
src_ss = inspect.getsource(scheduled_send)
check("TgForbidden except 분기 존재",
      "TgForbidden" in src_ss)
check("TgBadRequest except 분기 존재",
      "TgBadRequest" in src_ss)
check("Forbidden 분기에서 log.warning 사용",
      "log.warning" in src_ss)
check("Exception 분기에서 log.error 사용",
      "log.error" in src_ss)

# 2-2: Forbidden 순서가 Exception보다 먼저인지 확인
forbidden_idx  = src_ss.find("TgForbidden")
badreq_idx     = src_ss.find("TgBadRequest")
exception_idx  = src_ss.find("except Exception")
check("TgForbidden 핸들러가 Exception 핸들러보다 먼저 정의됨",
      0 <= forbidden_idx < exception_idx)
check("TgBadRequest 핸들러가 Exception 핸들러보다 먼저 정의됨",
      0 <= badreq_idx < exception_idx)

# 2-3: 런타임 — Forbidden 발생 시 warning만 기록 (error 없음)
UID = BASE_UID + 2
_clean(UID)
load_portfolios(UID)
state = _get_user_state(UID)
state["portfolios"]["p1"]["df"] = _make_df()
state["portfolios"]["p1"]["last_update"] = datetime.now()

from telegram.error import Forbidden as TgForbidden

warned = []
errored = []

async def _run_forbidden_test():
    # 실제 이벤트 루프의 run_in_executor를 no-op async 함수로 대체
    real_loop = asyncio.get_running_loop()
    _orig_rie  = real_loop.run_in_executor
    async def _noop_executor(executor, fn, *args):
        return None
    real_loop.run_in_executor = _noop_executor
    try:
        combined_bot.all_users[UID] = state
        with patch.object(combined_bot, "tg_bot") as mock_tg:
            mock_tg.send_message = AsyncMock(
                side_effect=TgForbidden("bot was blocked by the user")
            )
            _orig_warn = combined_bot.log.warning
            _orig_err  = combined_bot.log.error
            combined_bot.log.warning = lambda *a, **kw: warned.append(a)
            combined_bot.log.error   = lambda *a, **kw: errored.append(a)
            try:
                await scheduled_send("테스트")
            finally:
                combined_bot.log.warning = _orig_warn
                combined_bot.log.error   = _orig_err
    finally:
        real_loop.run_in_executor = _orig_rie
        combined_bot.all_users.pop(UID, None)

asyncio.run(_run_forbidden_test())

check("Forbidden 시 WARNING 로그 기록됨", len(warned) > 0)
check("Forbidden 시 ERROR 로그 미기록",   len(errored) == 0)

_clean(UID)


# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 3. build_user_html topnav 🔄 버튼 / build_combined_html 미포함")
print("="*60)

UID = BASE_UID + 3
_clean(UID)
load_portfolios(UID)
state = _get_user_state(UID)
state["portfolios"]["p1"]["df"] = _make_df()
state["portfolios"]["p1"]["last_update"] = datetime.now()
state["portfolios"]["p1"]["name"] = "테스트포트"

html = build_user_html(
    _make_df(), display_name="테스트포트",
    cashflows=[], pname="p1",
    all_portfolios=state["portfolios"], uid=UID, token="tok",
)

# 3-1: topnav 안에 topnav-refresh-btn 버튼 존재
topnav_start = html.find('<nav class="topnav">')
topnav_end   = html.find('</nav>', topnav_start)
topnav_html  = html[topnav_start:topnav_end] if topnav_start != -1 else ""

check("topnav 섹션 존재", topnav_start != -1)
check("topnav 안에 topnav-refresh-btn 버튼 존재",
      'id="topnav-refresh-btn"' in topnav_html)
check("topnav-refresh-btn 클릭 시 refreshPrices() 호출",
      'onclick="refreshPrices()"' in topnav_html)
check("topnav-refresh-btn에 🔄 이모지 포함", "🔄" in topnav_html)

# 3-2: refreshPrices() 함수가 topnav-refresh-btn 처리
check("refreshPrices가 topnav-refresh-btn getElementById 처리",
      "topnav-refresh-btn" in html)
check("refreshPrices 로딩 중 텍스트 '새로고침 중...' 사용",
      "새로고침 중..." in html)

# 3-3: nav-time이 topnav 버튼 뒤에 위치
btn_pos     = topnav_html.find("topnav-refresh-btn")
navtime_pos = topnav_html.find("nav-time")
check("nav-time이 topnav-refresh-btn 버튼 뒤에 위치",
      btn_pos != -1 and navtime_pos != -1 and navtime_pos > btn_pos)

# 3-4: build_combined_html — topnav-refresh-btn 미포함 (포트폴리오 dict 직접 구성)
combined_ports = {
    "p1": {"name": "주식포트",  "last_update": datetime.now(), "df": _make_df()},
    "p2": {"name": "두번째포트", "last_update": datetime.now(), "df": _make_df()},
}
combined_html = build_combined_html(UID, "tok", combined_ports)
check("build_combined_html topnav에 topnav-refresh-btn 미포함",
      "topnav-refresh-btn" not in combined_html)

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
