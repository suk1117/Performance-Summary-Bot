"""
파일 락 구조 수정 검증 테스트
  수정 1: save_portfolios — 단일 락 블록으로 TOCTOU 제거
  수정 2: _get_user_state — load_portfolios를 _users_lock 밖으로 이동
  수정 3: rename_portfolio — 미사용 TOCTOU 함수 삭제
"""
import sys, os, shutil, threading, inspect, time
sys.path.insert(0, os.path.dirname(__file__))

import combined_bot
from combined_bot import (
    DATA_DIR, _portfolios_file, _get_portfolios_file_lock,
    save_portfolios, _raw, _save_raw, get_user_token,
    all_users, _get_user_state, load_portfolios,
    app_flask, get_user_token, _users_lock,
    _cashflow_locks_lock, _cashflow_locks,
    _history_locks_lock, _history_locks,
)
import pandas as pd
import json

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name, cond):
    tag = PASS if cond else FAIL
    results.append((tag, name))
    print(f"  {tag}  {name}")

BASE_UID = 66660000

def _clean(uid):
    d = os.path.join(DATA_DIR, f"user_{uid}")
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)
    all_users.pop(uid, None)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 1-A: save_portfolios 코드 구조 — 단일 락 블록")
print("="*60)

src_sp = inspect.getsource(save_portfolios)
# _raw() / _save_raw() 직접 호출 없어야 함
check("save_portfolios: _raw() 직접 호출 없음", "_raw(uid)" not in src_sp)
check("save_portfolios: _save_raw() 직접 호출 없음", "_save_raw(" not in src_sp)
# 단일 락 블록 사용
check("save_portfolios: _get_portfolios_file_lock 사용", "_get_portfolios_file_lock" in src_sp)
check("save_portfolios: with lock 블록 안에서 파일 읽기", "with open" in src_sp)
check("save_portfolios: NamedTemporaryFile 사용", "NamedTemporaryFile" in src_sp)
check("save_portfolios: os.replace 사용", "os.replace" in src_sp)
# next_id·token 보존을 위한 기존 raw 읽기 후 items 덮어쓰기
check("save_portfolios: next_id 보존 (raw 재읽기 후 items 덮어씀)", "raw[\"items\"] = out" in src_sp or "raw['items'] = out" in src_sp)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 1-B: save_portfolios — token·next_id 보존 실동작")
print("="*60)

UID = BASE_UID + 1
_clean(UID)

# 토큰·next_id가 있는 초기 상태 세팅
initial = {
    "active": "p1", "next_id": 5, "token": "mytoken123",
    "items": {"p1": {"name": "테스트", "last_update": None, "df": []}}
}
_save_raw(UID, initial)

# save_portfolios 호출
state = _get_user_state(UID)
save_portfolios(UID, state["portfolios"], "p1")

after = _raw(UID)
check("save_portfolios 후 token 보존됨", after.get("token") == "mytoken123")
check("save_portfolios 후 next_id 보존됨", after.get("next_id") == 5)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 1-C: save_portfolios ↔ get_user_token 동시성 — token 소실 없음")
print("="*60)

UID = BASE_UID + 2
_clean(UID)
# 토큰 없는 초기 상태
_save_raw(UID, {"active": "p1", "next_id": 2,
                "items": {"p1": {"name": "포트", "last_update": None, "df": []}}})
state = _get_user_state(UID)

errors = []
token_results = []

def run_save():
    for _ in range(20):
        save_portfolios(UID, state["portfolios"], "p1")

def run_get_token():
    for _ in range(20):
        t = get_user_token(UID)
        token_results.append(t)

t1 = threading.Thread(target=run_save)
t2 = threading.Thread(target=run_get_token)
t1.start(); t2.start()
t1.join(); t2.join()

final = _raw(UID)
check("동시 실행 후 token 소실 없음", final.get("token") not in (None, ""))
check("token 값이 일관됨 (단일 값)", len(set(token_results)) == 1)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 2-A: _get_user_state 코드 구조 — load_portfolios 락 밖")
print("="*60)

src_gus = inspect.getsource(_get_user_state)
lines   = src_gus.splitlines()

load_idx = next((i for i, l in enumerate(lines) if "load_portfolios" in l), None)
lock_idx = next((i for i, l in enumerate(lines) if "with _users_lock" in l), None)

check("_get_user_state: load_portfolios 존재", load_idx is not None)
check("_get_user_state: _users_lock 존재", lock_idx is not None)
check("load_portfolios가 with _users_lock 보다 먼저 호출됨",
      load_idx is not None and lock_idx is not None and load_idx < lock_idx)
check("_users_lock 안에 load_portfolios 없음",
      # lock_idx 이후 라인에 load_portfolios가 없어야 함
      not any("load_portfolios" in l for l in lines[lock_idx+1:]) if lock_idx is not None else False)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 2-B: _get_user_state — 동시 로드 시 all_users 일관성")
print("="*60)

UID = BASE_UID + 3
_clean(UID)
_save_raw(UID, {"active": "p1", "next_id": 2,
                "items": {"p1": {"name": "포트", "last_update": None, "df": []}}})

loaded_states = []
errors2 = []

def load_state():
    try:
        s = _get_user_state(UID)
        loaded_states.append(id(s))
    except Exception as e:
        errors2.append(str(e))

threads = [threading.Thread(target=load_state) for _ in range(10)]
for t in threads: t.start()
for t in threads: t.join()

check("동시 로드 오류 없음", len(errors2) == 0)
check("all_users에 정확히 1개 항목", UID in all_users)
# 모든 스레드가 동일한 객체를 반환해야 함 (last-write-wins 허용)
check("모든 스레드가 같은 state 객체 반환", len(set(loaded_states)) == 1)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 3: rename_portfolio 삭제 확인")
print("="*60)

check("rename_portfolio 함수 삭제됨",
      not hasattr(combined_bot, "rename_portfolio"))
# api_rename_portfolio는 여전히 존재해야 함
check("api_rename_portfolio 라우트 존재",
      hasattr(combined_bot, "api_rename_portfolio"))

# api_rename_portfolio가 save_portfolios를 사용하는지 확인
from combined_bot import api_rename_portfolio
src_arp = inspect.getsource(api_rename_portfolio)
check("api_rename_portfolio: save_portfolios 사용",
      "save_portfolios" in src_arp)
# "api_rename_portfolio(" 자체가 "rename_portfolio(" 포함 → def 라인 제외 후 확인
src_arp_body = "\n".join(l for l in src_arp.splitlines() if not l.strip().startswith("def "))
check("api_rename_portfolio: rename_portfolio 미호출",
      "rename_portfolio(" not in src_arp_body)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 3-B: api_rename_portfolio 실동작 — 이름 변경 디스크 반영")
print("="*60)

UID = BASE_UID + 4
_clean(UID)
load_portfolios(UID)
state = _get_user_state(UID)
token = get_user_token(UID)
client = app_flask.test_client()

with app_flask.app_context():
    resp = client.patch(
        f"/u/{UID}/api/portfolios/p1?t={token}",
        json={"name": "새이름포트"}
    )

check("api_rename_portfolio HTTP 200", resp.status_code == 200)

# 인메모리 확인
check("인메모리 이름 변경됨",
      state["portfolios"]["p1"]["name"] == "새이름포트")

# 디스크 재로드 확인
all_users.pop(UID, None)
state2 = _get_user_state(UID)
check("디스크에서 재로드 후 이름 일치",
      state2["portfolios"]["p1"]["name"] == "새이름포트")

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 통합: 포트폴리오 삭제 — save_portfolios 단일 경로 확인")
print("="*60)

UID = BASE_UID + 5
_clean(UID)
load_portfolios(UID)
state = _get_user_state(UID)
token = get_user_token(UID)
client2 = app_flask.test_client()

# p2 생성
with app_flask.app_context():
    r = client2.post(f"/u/{UID}/api/portfolios?t={token}", json={"name": "삭제대상"})
check("p2 생성 성공", r.status_code == 200)
p2 = r.get_json()["pname"]

# p2 삭제
with app_flask.app_context():
    r2 = client2.delete(f"/u/{UID}/api/portfolios/{p2}?t={token}")
check("포트폴리오 삭제 HTTP 200", r2.status_code == 200)

# 디스크 재로드 후 확인
all_users.pop(UID, None)
state3 = _get_user_state(UID)
check("삭제 후 p1만 남음", list(state3["portfolios"].keys()) == ["p1"])
check("디스크에서 재로드 후에도 p2 없음", p2 not in state3["portfolios"])

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
