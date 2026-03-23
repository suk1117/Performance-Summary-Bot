"""
데이터 소실 버그 수정 테스트
  1. 원자적 쓰기 — tempfile + os.replace (_save_raw, save_cashflow, save_snapshot)
  2. api_add_stock df 읽기/수정 락 안에 위치
  3. 동시 종목 추가 race condition 방지
"""
import sys, os, shutil, threading, inspect
sys.path.insert(0, os.path.dirname(__file__))

import combined_bot
from combined_bot import (
    DATA_DIR, _save_raw, save_cashflow, save_snapshot,
    _raw, load_cashflow, _portfolios_file, _user_dir,
    all_users, _get_user_state, load_portfolios,
    app_flask, get_user_token, add_cashflow,
    _users_lock, api_add_stock,
)
import pandas as pd
from datetime import datetime

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name, cond):
    tag = PASS if cond else FAIL
    results.append((tag, name))
    print(f"  {tag}  {name}")

BASE_UID = 44440000

def _clean(uid):
    d = os.path.join(DATA_DIR, f"user_{uid}")
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)
    all_users.pop(uid, None)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 1. 원자적 쓰기 — 코드 구조 검증")
print("="*60)

src_sr = inspect.getsource(_save_raw)
check("_save_raw: NamedTemporaryFile 사용", "NamedTemporaryFile" in src_sr)
check("_save_raw: os.replace 사용", "os.replace" in src_sr)
check("_save_raw: open('w') 직접 쓰기 없음", 'open(_portfolios_file' not in src_sr)

src_sc = inspect.getsource(save_cashflow)
check("save_cashflow: NamedTemporaryFile 사용", "NamedTemporaryFile" in src_sc)
check("save_cashflow: os.replace 사용", "os.replace" in src_sc)

from combined_bot import _save_snapshot_inner
src_ss = inspect.getsource(_save_snapshot_inner)
check("save_snapshot: NamedTemporaryFile 사용", "NamedTemporaryFile" in src_ss)
check("save_snapshot: os.replace 사용", "os.replace" in src_ss)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 2. 원자적 쓰기 — 실제 동작 검증")
print("="*60)

UID = BASE_UID + 1
_clean(UID)
load_portfolios(UID)

data = {
    "active": "p1", "next_id": 2,
    "items": {"p1": {"name": "테스트포트", "last_update": None,
                     "df": [{"종목명": "삼성전자", "국가": "KR", "비중(%)": 100.0,
                             "평단가": 70000.0, "수량": 10.0, "통화": "KRW"}]}}
}
_save_raw(UID, data)
loaded = _raw(UID)
check("_save_raw 저장/로드 정상", loaded.get("items", {}).get("p1", {}).get("name") == "테스트포트")
check("종목 데이터 보존됨", len(loaded["items"]["p1"]["df"]) == 1)

user_dir = _user_dir(UID)
tmp_files = [f for f in os.listdir(user_dir) if f.endswith(".tmp")]
check(".tmp 임시파일 정리됨 (정상 완료)", len(tmp_files) == 0)

add_cashflow(UID, "p1", "in", 2_000_000, "테스트입금")
records = load_cashflow(UID, "p1")
check("save_cashflow 저장/로드 정상", len(records) == 1 and records[0]["amount"] == 2_000_000)
tmp_files2 = [f for f in os.listdir(user_dir) if f.endswith(".tmp")]
check("cashflow .tmp 파일 정리됨", len(tmp_files2) == 0)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 3. api_add_stock — df 전체 연산이 락 안에 위치")
print("="*60)

src = inspect.getsource(api_add_stock)
lines = src.splitlines()
lock_idx  = next((i for i, l in enumerate(lines) if "with _users_lock:" in l), None)
copy_idx  = next((i for i, l in enumerate(lines) if ".copy()" in l and "df" in l), None)
concat_idx = next((i for i, l in enumerate(lines) if "pd.concat" in l), None)
save_idx  = next((i for i, l in enumerate(lines) if "save_portfolios" in l), None)

check("with _users_lock 존재", lock_idx is not None)
check(".copy()가 락 안에 위치", lock_idx is not None and copy_idx is not None and copy_idx > lock_idx)
check("pd.concat이 락 안에 위치", lock_idx is not None and concat_idx is not None and concat_idx > lock_idx)
check("save_portfolios가 락 안에 위치", lock_idx is not None and save_idx is not None and save_idx > lock_idx)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" 4. 동시 종목 추가 — race condition 방지")
print("="*60)

UID = BASE_UID + 2
_clean(UID)
load_portfolios(UID)
state = _get_user_state(UID)
token = get_user_token(UID)

errors = []
client = app_flask.test_client()

def add_stock(stock_name):
    payload = {"종목명": stock_name, "국가": "KR", "수량": 1.0, "평단가": 10000.0}
    with app_flask.app_context():
        resp = client.post(f"/u/{UID}/api/p/p1/stock?t={token}", json=payload)
    if resp.status_code != 200:
        errors.append(f"{stock_name}: {resp.status_code} {resp.data}")

threads = [threading.Thread(target=add_stock, args=(f"종목{i}",)) for i in range(5)]
for t in threads: t.start()
for t in threads: t.join()

all_users.pop(UID, None)
state2 = _get_user_state(UID)
df_result = state2["portfolios"]["p1"]["df"]

check("동시 추가 오류 없음", len(errors) == 0)
check("5개 종목 모두 저장됨 (race condition 없음)", len(df_result) == 5)

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
