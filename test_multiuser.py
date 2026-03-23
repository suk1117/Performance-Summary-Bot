"""
멀티유저 격리 테스트
- 실제 data/ 디렉토리에 임시 유저 데이터를 생성해 테스트 후 정리
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import json
import shutil
import pandas as pd

# combined_bot 에서 storage 함수 직접 임포트
from combined_bot import (
    _user_dir, _portfolios_file,
    load_portfolios, save_portfolios, create_portfolio,
    add_cashflow, get_net_investment, load_cashflow,
    save_snapshot, load_history,
    get_user_token,
    DATA_DIR,
)

# ── 테스트용 UID ───────────────────────────────────────────
MY_UID    = 11111111   # 내 계정 (가상)
OTHER_UID = 99999999   # 다른 유저 (가상)

PASS = "✅ PASS"
FAIL = "❌ FAIL"

results = []

def check(name, cond):
    tag = PASS if cond else FAIL
    results.append((tag, name))
    print(f"  {tag}  {name}")

print("\n" + "="*60)
print(" 멀티유저 격리 테스트 시작")
print("="*60)

# ── 0. 기존 테스트 데이터 정리 ─────────────────────────────
for uid in [MY_UID, OTHER_UID]:
    d = os.path.join(DATA_DIR, f"user_{uid}")
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)

# ── 1. 최초 접속 시 각자 독립 디렉토리 생성 ──────────────
print("\n[1] 최초 접속 - 디렉토리 격리")
_ = load_portfolios(MY_UID)
_ = load_portfolios(OTHER_UID)
check("내 유저 디렉토리 생성", os.path.isdir(os.path.join(DATA_DIR, f"user_{MY_UID}")))
check("다른 유저 디렉토리 생성", os.path.isdir(os.path.join(DATA_DIR, f"user_{OTHER_UID}")))
check("두 디렉토리가 다름", _user_dir(MY_UID) != _user_dir(OTHER_UID))

# ── 2. 포트폴리오 데이터 격리 ─────────────────────────────
print("\n[2] 포트폴리오 데이터 격리")
my_portfolios, my_active = load_portfolios(MY_UID)
other_portfolios, other_active = load_portfolios(OTHER_UID)

# 내 계정에 삼성전자 추가
my_portfolios[my_active]["df"] = pd.DataFrame([{
    "종목명": "삼성전자", "국가": "KR", "비중(%)": 50.0,
    "평단가": 70000.0, "수량": 10.0, "통화": "KRW",
    "현재가": 75000.0, "수익률(%)": 7.14, "등락률(%)": 0.5, "USD_KRW": 1300.0,
}])
my_portfolios[my_active]["last_update"] = pd.Timestamp.now()
save_portfolios(MY_UID, my_portfolios, my_active)

# 다른 유저 포트폴리오 다시 로드해서 내 데이터가 없는지 확인
other_portfolios2, _ = load_portfolios(OTHER_UID)
other_df = other_portfolios2[other_active]["df"]
check("다른 유저 포트폴리오에 내 종목 없음", "삼성전자" not in other_df.get("종목명", pd.Series()).values)
check("내 포트폴리오에 삼성전자 있음", "삼성전자" in my_portfolios[my_active]["df"]["종목명"].values)

# ── 3. 포트폴리오 개수 독립 ───────────────────────────────
print("\n[3] 포트폴리오 생성 독립")
create_portfolio(MY_UID, "해외주식")
create_portfolio(MY_UID, "채권")
create_portfolio(OTHER_UID, "OTHER전용")

my_p2, _   = load_portfolios(MY_UID)
other_p2, _ = load_portfolios(OTHER_UID)
check(f"내 계정 포트폴리오 3개", len(my_p2) == 3)
check(f"다른 유저 포트폴리오 2개 (기본+OTHER전용)", len(other_p2) == 2)
check("포트폴리오 이름 겹치지 않음",
      not any(n in [p["name"] for p in other_p2.values()]
              for n in [p["name"] for p in my_p2.values()
                        if p["name"] not in ("기본 포트폴리오",)]))

# ── 4. 자금 기록 격리 ─────────────────────────────────────
print("\n[4] 자금 기록(cashflow) 격리")
add_cashflow(MY_UID, my_active, "in", 10_000_000, "내 입금")
add_cashflow(OTHER_UID, other_active, "in", 5_000_000, "타인 입금")

my_net   = get_net_investment(MY_UID, my_active)
other_net = get_net_investment(OTHER_UID, other_active)
check("내 순투자금 10,000,000", my_net == 10_000_000)
check("다른 유저 순투자금 5,000,000", other_net == 5_000_000)
check("자금 기록 상호 독립", my_net != other_net)

# 내 cashflow 파일이 다른 유저 디렉토리에 없는지 확인
other_cashflow_path = os.path.join(_user_dir(OTHER_UID), f"cashflow_{my_active}.json")
# other_uid 디렉토리 내 cashflow 읽어서 내 입금 메모 없는지 확인
other_cf = load_cashflow(OTHER_UID, other_active)
check("다른 유저 cashflow에 '내 입금' 없음",
      all(r["memo"] != "내 입금" for r in other_cf))

# ── 5. URL 토큰 격리 ──────────────────────────────────────
print("\n[5] 대시보드 URL 토큰 격리")
my_token    = get_user_token(MY_UID)
other_token = get_user_token(OTHER_UID)
check("내 토큰 생성됨 (16자 이상)", len(my_token) >= 16)
check("다른 유저 토큰 생성됨", len(other_token) >= 16)
check("토큰이 서로 다름", my_token != other_token)

# ── 6. 파일 경로 완전 분리 확인 ───────────────────────────
print("\n[6] 파일 경로 물리적 분리")
my_file    = _portfolios_file(MY_UID)
other_file = _portfolios_file(OTHER_UID)
check("portfolios.json 경로 다름", my_file != other_file)
check("내 파일 존재",    os.path.isfile(my_file))
check("다른 유저 파일 존재", os.path.isfile(other_file))

# 파일 내용에 상대방 데이터 없는지 확인
with open(my_file, encoding="utf-8") as f:
    my_raw_text = f.read()
with open(other_file, encoding="utf-8") as f:
    other_raw_text = f.read()
check("내 파일에 삼성전자 있음", "삼성전자" in my_raw_text)
check("다른 유저 파일에 삼성전자 없음", "삼성전자" not in other_raw_text)

# ── 정리 ──────────────────────────────────────────────────
for uid in [MY_UID, OTHER_UID]:
    d = os.path.join(DATA_DIR, f"user_{uid}")
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)
print("\n[테스트 데이터 삭제 완료]")

# ── 결과 요약 ─────────────────────────────────────────────
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
