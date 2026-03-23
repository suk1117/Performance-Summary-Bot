"""
수정 검증 테스트
  수정 1: create_portfolio ↔ save_portfolios 경쟁 조건 제거
  수정 2: 재시작 후 타 유저 스케줄러 미작동 — 디스크 전체 유저 로드
"""
import sys, os, shutil, threading, inspect
sys.path.insert(0, os.path.dirname(__file__))

import combined_bot
from combined_bot import (
    DATA_DIR, _save_raw, save_portfolios, create_portfolio,
    _raw, _user_dir, all_users, _get_user_state, load_portfolios,
    app_flask, get_user_token, _users_lock,
)
import pandas as pd

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

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 1-A: create_portfolio 코드 구조 검증")
print("="*60)

src_cp = inspect.getsource(create_portfolio)
# items를 raw에 직접 쓰지 않아야 함
check("create_portfolio: raw['items'] 직접 쓰기 없음", "raw[\"items\"]" not in src_cp and "raw['items']" not in src_cp)
# next_id는 여전히 디스크에 기록
check("create_portfolio: next_id 갱신 유지", "next_id" in src_cp and "os.replace" in src_cp)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 1-B: api_create_portfolio 코드 구조 검증")
print("="*60)

from combined_bot import api_create_portfolio
src_api = inspect.getsource(api_create_portfolio)
lines   = src_api.splitlines()

lock_idx  = next((i for i, l in enumerate(lines) if "with _users_lock:" in l), None)
save_idx  = next((i for i, l in enumerate(lines) if "save_portfolios" in l), None)
add_idx   = next((i for i, l in enumerate(lines) if "state[\"portfolios\"][pname]" in l or "state['portfolios'][pname]" in l), None)

check("api_create_portfolio: _users_lock 사용", lock_idx is not None)
check("api_create_portfolio: save_portfolios 호출", save_idx is not None)
check("인메모리 추가가 락 안에 위치", lock_idx is not None and add_idx is not None and add_idx > lock_idx)
check("save_portfolios가 락 안에 위치", lock_idx is not None and save_idx is not None and save_idx > lock_idx)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 1-C: create_portfolio 실제 동작 — items 덮어쓰기 없음")
print("="*60)

UID = BASE_UID + 1
_clean(UID)

# 기존 데이터 세팅
existing = {
    "active": "p1", "next_id": 2,
    "items": {
        "p1": {"name": "기존포트", "last_update": None,
               "df": [{"종목명": "삼성전자", "국가": "KR", "비중(%)": 100.0,
                        "평단가": 70000.0, "수량": 10.0, "통화": "KRW"}]}
    }
}
_save_raw(UID, existing)

# create_portfolio 호출 (이전엔 items를 빈 df로 덮어썼음)
pname = create_portfolio(UID, "새포트")

raw_after = _raw(UID)
check("create_portfolio 후 기존 p1 items 보존됨", "p1" in raw_after.get("items", {}))
check("기존 p1 종목 데이터 유지됨",
      len(raw_after.get("items", {}).get("p1", {}).get("df", [])) == 1)
check("next_id 정상 증가", raw_after.get("next_id") == 3)
check("새 pname은 p2", pname == "p2")
# create_portfolio가 새 포트를 items에 쓰지 않음 (저장은 호출자 몫)
check("create_portfolio 단독으론 p2 items에 쓰지 않음", "p2" not in raw_after.get("items", {}))

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 1-D: api_create_portfolio — 인메모리+디스크 동기화")
print("="*60)

UID = BASE_UID + 2
_clean(UID)
load_portfolios(UID)
state = _get_user_state(UID)
token = get_user_token(UID)
client = app_flask.test_client()

with app_flask.app_context():
    resp = client.post(
        f"/u/{UID}/api/portfolios?t={token}",
        json={"name": "API생성포트"}
    )

check("api_create_portfolio HTTP 200", resp.status_code == 200)
data = resp.get_json()
check("응답에 pname 포함", data is not None and "pname" in data)

if data and "pname" in data:
    new_pname = data["pname"]
    # 인메모리 확인
    check("인메모리에 새 포트 존재", new_pname in state["portfolios"])
    # 디스크 확인
    all_users.pop(UID, None)
    state2 = _get_user_state(UID)
    check("디스크에서 재로드 후에도 새 포트 존재", new_pname in state2["portfolios"])
    check("재로드 후 포트 이름 일치", state2["portfolios"][new_pname]["name"] == "API생성포트")

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 1-E: 경쟁 조건 — 동시 포트폴리오 생성")
print("="*60)

UID = BASE_UID + 3
_clean(UID)
load_portfolios(UID)
state = _get_user_state(UID)
token = get_user_token(UID)
client2 = app_flask.test_client()

errors = []
created_pnames = []
lock_pnames = threading.Lock()

def create_p(name):
    with app_flask.app_context():
        r = client2.post(f"/u/{UID}/api/portfolios?t={token}", json={"name": name})
    if r.status_code == 200:
        with lock_pnames:
            created_pnames.append(r.get_json()["pname"])
    else:
        errors.append(f"{name}: {r.status_code}")

threads = [threading.Thread(target=create_p, args=(f"포트{i}",)) for i in range(5)]
for t in threads: t.start()
for t in threads: t.join()

check("동시 생성 오류 없음", len(errors) == 0)
check("5개 포트 모두 고유 pname", len(set(created_pnames)) == 5)

# 디스크 재로드해서 5개 모두 있는지 확인
all_users.pop(UID, None)
state3 = _get_user_state(UID)
check("디스크에 5개 포트 모두 저장됨 (기본 p1 포함 총 6개)", len(state3["portfolios"]) == 6)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 2-A: main() 코드 구조 — 전체 유저 로드 로직")
print("="*60)

src_main = inspect.getsource(combined_bot.main)
check("main: os.scandir 사용", "os.scandir" in src_main)
check("main: user_ 폴더 필터링", "startswith(\"user_\")" in src_main or 'startswith("user_")' in src_main)
check("main: _get_user_state 루프 내 호출", src_main.count("_get_user_state") >= 2)
check("main: 단일 유저 로드 코드 제거됨", "기본 유저 포트폴리오" not in src_main)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 수정 2-B: 실제 동작 — 디스크 유저 스캔 후 all_users 로드")
print("="*60)

UID_A = BASE_UID + 10
UID_B = BASE_UID + 11
UID_C = BASE_UID + 12
for u in [UID_A, UID_B, UID_C]:
    _clean(u)

# 디스크에 3개 유저 데이터 미리 생성
for u in [UID_A, UID_B, UID_C]:
    _save_raw(u, {
        "active": "p1", "next_id": 2,
        "items": {"p1": {"name": f"포트_{u}", "last_update": None, "df": []}}
    })
    all_users.pop(u, None)  # 메모리에서 제거 (재시작 시뮬레이션)

# main()의 scandir 로직 직접 실행
_loaded = 0
if os.path.isdir(DATA_DIR):
    for _entry in os.scandir(DATA_DIR):
        if _entry.is_dir() and _entry.name.startswith("user_"):
            try:
                _uid = int(_entry.name.split("_", 1)[1])
                if _uid in [UID_A, UID_B, UID_C]:  # 테스트 유저만
                    _get_user_state(_uid)
                    _loaded += 1
            except (ValueError, Exception):
                pass

check("3명 유저 모두 all_users에 로드됨",
      UID_A in all_users and UID_B in all_users and UID_C in all_users)
check("로드 카운트 정확함", _loaded == 3)
check("각 유저 포트폴리오 데이터 유지됨",
      all([all_users[u]["portfolios"]["p1"]["name"] == f"포트_{u}"
           for u in [UID_A, UID_B, UID_C]]))

for u in [UID_A, UID_B, UID_C]:
    _clean(u)

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
