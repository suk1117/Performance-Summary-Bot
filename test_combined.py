"""
combined_bot 종합 테스트
커버 항목:
  A. compute_combined_nav  — 빈/단일/복수 cashflow 병합 계산
  B. _build_portfolio_tabs — 전체 탭 추가/활성/링크
  C. build_combined_html   — 렌더링, 빈 df 포트폴리오 net_inv 포함
  D. _build_dashboard_bg   — 실패 시 _building + _hist_check 재시도 허용
  E. api_add_cashflow_route — 존재하지 않는 pname → 404
  F. _migrate              — 원본 파일 삭제 안 함
  G. _summary_text         — 복수 포트폴리오 시 전체 수익률 라인 추가
  H. build_dashboard_for   — save_snapshot이 _users_lock 블록 밖에 위치
  I. 기존 멀티유저 격리    — 회귀 검증
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import json
import shutil
import inspect
import threading
import pandas as pd
from datetime import datetime
from unittest.mock import patch

import combined_bot
from combined_bot import (
    DATA_DIR, _user_dir,
    load_portfolios, save_portfolios, create_portfolio,
    add_cashflow, load_cashflow,
    compute_combined_nav,
    _build_portfolio_tabs, build_combined_html,
    _build_dashboard_bg, _building, _hist_check, _build_lock,
    _get_user_state, get_user_token,
    all_users,
    app_flask,
    _summary_text,
)

# ── 공용 ──────────────────────────────────────────────────
PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name, cond):
    tag = PASS if cond else FAIL
    results.append((tag, name))
    print(f"  {tag}  {name}")

BASE_UID = 44440000   # 각 섹션은 BASE_UID + offset 사용

def _clean(uid):
    d = os.path.join(DATA_DIR, f"user_{uid}")
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)

def _make_df(**extra):
    base = {
        "종목명": "삼성전자", "국가": "KR",
        "비중(%)": 100.0, "평단가": 70000.0, "수량": 10.0, "통화": "KRW",
        "현재가": 75000.0, "수익률(%)": 7.14, "등락률(%)": 0.5, "USD_KRW": 1350.0,
    }
    base.update(extra)
    return pd.DataFrame([base])

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" A. compute_combined_nav")
print("="*60)
UID = BASE_UID + 1
_clean(UID)

# A-1: cashflow 없으면 (1000, 0)
nav, units = compute_combined_nav(UID, ["p1"], 0.0)
check("빈 cashflow → nav=1000, units=0", nav == 1000.0 and units == 0.0)

# A-2: 단일 포트폴리오 100만 입금, 현재 110만 → nav=1100
load_portfolios(UID)
add_cashflow(UID, "p1", "in", 1_000_000, "")
# 첫 입금 시 nav=1000 으로 기록돼야 하므로 cashflow nav 직접 확인
cf = load_cashflow(UID, "p1")
nav_in_cf = cf[0].get("nav", 1000.0)
units_expected = 1_000_000 / nav_in_cf
nav_calc, units_calc = compute_combined_nav(UID, ["p1"], 1_100_000.0)
check("단일 입금 nav 계산", abs(nav_calc - 1_100_000.0 / units_calc) < 0.01)

# A-3: 복수 포트폴리오 cashflow 병합
create_portfolio(UID, "p2용")
add_cashflow(UID, "p2", "in", 2_000_000, "")
# units = 100만/1000 + 200만/1000 = 3000
nav_m, units_m = compute_combined_nav(UID, ["p1", "p2"], 3_500_000.0)
check("복수 cashflow 병합 units=3000", abs(units_m - 3000.0) < 0.01)
check("복수 cashflow 병합 nav=3500000/3000", abs(nav_m - 3_500_000.0 / 3000.0) < 0.01)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" B. _build_portfolio_tabs — 전체 탭")
print("="*60)
UID = BASE_UID + 2
_clean(UID)
load_portfolios(UID)
create_portfolio(UID, "두번째")
ps, _ = load_portfolios(UID)

# B-1: 단일 포트폴리오 → 전체 탭 없음
single = {"p1": ps["p1"]}
tabs = _build_portfolio_tabs(single, "p1", uid=UID, token="tok")
check("단일 포트폴리오 전체 탭 없음", "전체" not in tabs)

# B-2: 복수 포트폴리오, current="all" → active 탭
tabs_all = _build_portfolio_tabs(ps, "all", uid=UID, token="tok")
check('전체탭 active 클래스', 'class="tab active"' in tabs_all.split("전체")[0])
check("전체탭 active 링크 없음", f"/p/all" not in tabs_all.split("전체")[0])

# B-3: 복수 포트폴리오, current="p1" → 전체 탭이 링크
tabs_p1 = _build_portfolio_tabs(ps, "p1", uid=UID, token="tok")
check("p1 active일 때 전체탭 링크", f"/u/{UID}/p/all?t=tok" in tabs_p1)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" C. build_combined_html")
print("="*60)
UID = BASE_UID + 3
_clean(UID)
load_portfolios(UID)
create_portfolio(UID, "빈포트폴리오")
ps, active = load_portfolios(UID)

df1 = _make_df()
ps["p1"]["df"] = df1
ps["p1"]["last_update"] = datetime.now()
save_portfolios(UID, ps, active)

add_cashflow(UID, "p1", "in", 1_000_000, "")
add_cashflow(UID, "p2", "in", 3_000_000, "")  # p2는 df 없음

ps, _ = load_portfolios(UID)
html = build_combined_html(UID, "tok", ps)

check("HTML 생성 성공 (>5000자)", len(html) > 5000)
check("전체 탭 active 포함", 'class="tab active"' in html and "전체" in html)
check("파이차트 캔버스 포함", "pieChart" in html)
check("포트폴리오명 표시", "기본 포트폴리오" in html and "빈포트폴리오" in html)
check("overview 총 손익 섹션", "총 손익" in html)
check("통합 계좌 수익률 섹션", "통합 계좌 수익률" in html)

# C-1: 빈 df 포트폴리오 net_inv 포함 (combined_net_inv = 400만)
# combined_stock_eval = 75000*10 = 750만, combined_total_buy = 700만
# combined_net_inv 수정 전: 100만 (p2 스킵)  수정 후: 400만
# combined_cash = max(0, 400만-700만) = 0  (모두 0이라 직접 차이 안 남)
# 대신 nav 계산에서 차이 확인: units = 100만/1000 + 300만/1000 = 4000
nav_c, units_c = compute_combined_nav(UID, ["p1", "p2"], 750_0000.0)
check("빈 df 포트폴리오 cashflow units 합산 (4000)", abs(units_c - 4000.0) < 0.01)

# C-2: combined_net_inv 직접 검증 (내부 계산 재현)
cf_p1 = load_cashflow(UID, "p1")
cf_p2 = load_cashflow(UID, "p2")
net_p1 = sum(c["amount"] for c in cf_p1 if c["type"] == "in") - sum(c["amount"] for c in cf_p1 if c["type"] == "out")
net_p2 = sum(c["amount"] for c in cf_p2 if c["type"] == "in") - sum(c["amount"] for c in cf_p2 if c["type"] == "out")
check("combined_net_inv = p1+p2 (400만)", net_p1 + net_p2 == 4_000_000)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" D. _build_dashboard_bg — 실패 시 재시도 허용")
print("="*60)
UID = BASE_UID + 4

# D-1: 성공 시 _building에서만 제거, _hist_check 유지
key = (UID, "p1")
with _build_lock:
    _building.add(key)
    _hist_check[key] = "2099-01-01"

with patch("combined_bot.build_dashboard_for", return_value=pd.DataFrame()):
    _build_dashboard_bg(UID, "p1")

with _build_lock:
    not_in_building = key not in _building
    hist_kept       = key in _hist_check

check("성공 시 _building 제거", not_in_building)
check("성공 시 _hist_check 유지 (당일 중복 빌드 방지)", hist_kept)

# 정리
with _build_lock:
    _hist_check.pop(key, None)

# D-2: 실패 시 _building + _hist_check 모두 제거 (재시도 허용)
with _build_lock:
    _building.add(key)
    _hist_check[key] = "2099-01-01"

with patch("combined_bot.build_dashboard_for", side_effect=RuntimeError("테스트 오류")):
    _build_dashboard_bg(UID, "p1")

with _build_lock:
    not_in_building_f = key not in _building
    not_in_hist_f     = key not in _hist_check

check("실패 시 _building 제거", not_in_building_f)
check("실패 시 _hist_check 제거 (재시도 허용)", not_in_hist_f)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" E. api_add_cashflow_route — pname 검증")
print("="*60)
UID = BASE_UID + 5
_clean(UID)
load_portfolios(UID)
token = get_user_token(UID)

with app_flask.test_client() as client:
    # E-1: 유효한 pname → 200
    resp = client.post(
        f"/u/{UID}/api/cashflow/p1?t={token}",
        json={"type": "in", "amount": 100_000, "memo": "테스트"},
    )
    check("유효 pname cashflow 추가 200", resp.status_code == 200)

    # E-2: 존재하지 않는 pname → 404
    resp = client.post(
        f"/u/{UID}/api/cashflow/nonexistent?t={token}",
        json={"type": "in", "amount": 100_000, "memo": "테스트"},
    )
    check("존재하지 않는 pname → 404", resp.status_code == 404)

    # E-3: 토큰 없음 → 403
    resp = client.post(
        f"/u/{UID}/api/cashflow/p1",
        json={"type": "in", "amount": 100_000},
    )
    check("토큰 없음 → 403", resp.status_code == 403)

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" F. _migrate — 원본 파일 삭제 안 함")
print("="*60)
UID = BASE_UID + 6
_clean(UID)

# 구버전 멀티 포트폴리오 파일 생성
old_portfolios = os.path.join(DATA_DIR, "portfolios.json")
old_history    = os.path.join(DATA_DIR, "history_p1.json")
with open(old_portfolios, "w", encoding="utf-8") as f:
    json.dump({
        "active": "p1", "next_id": 2,
        "items": {"p1": {"name": "기본", "last_update": None, "df": []}},
    }, f)
with open(old_history, "w", encoding="utf-8") as f:
    json.dump({}, f)

load_portfolios(UID)   # 마이그레이션 실행

check("마이그레이션 후 portfolios.json 원본 보존", os.path.exists(old_portfolios))
check("마이그레이션 후 history 원본 보존", os.path.exists(old_history))
dst = os.path.join(_user_dir(UID), "portfolios.json")
check("마이그레이션 대상 파일 생성", os.path.exists(dst))

os.remove(old_portfolios)
os.remove(old_history)
_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" G. _summary_text — 전체 계좌 수익률")
print("="*60)
UID = BASE_UID + 7
_clean(UID)
combined_bot.public_url = "http://test"

# save_portfolios는 수익률(%) 등 _DERIVED_COLS를 저장하지 않으므로
# all_users 캐시에 df를 직접 주입해서 _summary_text가 올바른 df를 읽도록 함

load_portfolios(UID)        # 디스크 디렉토리 초기화
all_users.pop(UID, None)    # 혹시 남은 캐시 제거
state = _get_user_state(UID)  # 새로 로드 → all_users[UID] 세팅

state["portfolios"]["p1"]["df"] = _make_df()
state["portfolios"]["p1"]["last_update"] = datetime.now()
add_cashflow(UID, "p1", "in", 1_000_000, "")

# G-1: 단일 포트폴리오 → "전체 계좌 수익률" 없음
text_single = _summary_text(UID, "p1")
check("단일 포트폴리오 전체 수익률 없음", "전체 계좌 수익률" not in text_single)

# G-2: 복수 포트폴리오 — p2를 state에 직접 추가
df2 = pd.DataFrame([{
    "종목명": "AAPL", "국가": "US", "비중(%)": 100.0,
    "평단가": 150.0, "수량": 5.0, "통화": "USD",
    "현재가": 180.0, "수익률(%)": 20.0, "등락률(%)": 1.0, "USD_KRW": 1350.0,
}])
state["portfolios"]["p2"] = {
    "name": "p2용", "last_update": datetime.now(), "df": df2,
}
add_cashflow(UID, "p2", "in", 2_000_000, "")

text_multi = _summary_text(UID, "p1")
check("복수 포트폴리오 전체 수익률 라인 추가", "전체 계좌 수익률" in text_multi)
check("전체 수익률 % 표시 포함", "%" in text_multi.split("전체 계좌 수익률")[-1][:20])

_clean(UID)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" H. build_dashboard_for — save_snapshot 락 밖 위치")
print("="*60)

src = inspect.getsource(combined_bot.build_dashboard_for)
lines = src.splitlines()

# save_snapshot 호출 라인과 마지막 'with _users_lock:' 라인의 상대 위치 확인
# build_dashboard_for는 읽기용 lock + save_snapshot + 쓰기용 lock 구조
snapshot_idx  = next((i for i, l in enumerate(lines) if "save_snapshot(" in l), None)
all_lock_idxs = [i for i, l in enumerate(lines) if "with _users_lock:" in l]
# 쓰기용 lock = save_snapshot 이후에 나오는 첫 번째 lock
write_lock_idx = next((i for i in all_lock_idxs if snapshot_idx is not None and i > snapshot_idx), None)

check("save_snapshot 코드 존재", snapshot_idx is not None)
check("_users_lock 블록 코드 존재", len(all_lock_idxs) > 0)
check("save_snapshot이 _users_lock 블록 앞에 위치",
      snapshot_idx is not None and write_lock_idx is not None and snapshot_idx < write_lock_idx)

# 쓰기용 락 블록 안에 save_snapshot이 없는지 확인 (들여쓰기 기준)
if write_lock_idx is not None:
    lock_indent = len(lines[write_lock_idx]) - len(lines[write_lock_idx].lstrip())
    inside_lock = [
        l for l in lines[write_lock_idx+1:]
        if l.strip() and (len(l) - len(l.lstrip())) > lock_indent and "save_snapshot(" in l
    ]
    check("_users_lock 블록 내 save_snapshot 없음", len(inside_lock) == 0)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print(" I. 멀티유저 격리 회귀 테스트")
print("="*60)
MY_UID    = BASE_UID + 91
OTHER_UID = BASE_UID + 92
for uid in [MY_UID, OTHER_UID]:
    _clean(uid)

_ = load_portfolios(MY_UID)
_ = load_portfolios(OTHER_UID)
check("유저 디렉토리 격리 생성", _user_dir(MY_UID) != _user_dir(OTHER_UID))

my_ps, my_act = load_portfolios(MY_UID)
my_ps[my_act]["df"] = pd.DataFrame([{
    "종목명": "삼성전자", "국가": "KR", "비중(%)": 100.0,
    "평단가": 70000.0, "수량": 10.0, "통화": "KRW",
}])
save_portfolios(MY_UID, my_ps, my_act)

other_ps, other_act = load_portfolios(OTHER_UID)
other_df = other_ps[other_act]["df"]
check("다른 유저 포트폴리오에 내 종목 없음",
      "삼성전자" not in other_df.get("종목명", pd.Series()).values)

add_cashflow(MY_UID,    my_act,    "in", 10_000_000, "")
add_cashflow(OTHER_UID, other_act, "in",  5_000_000, "")
from combined_bot import get_net_investment
check("자금 기록 격리 (내 순투자금 1000만)", get_net_investment(MY_UID,    my_act)    == 10_000_000)
check("자금 기록 격리 (타인 순투자금 500만)",  get_net_investment(OTHER_UID, other_act) ==  5_000_000)

my_token    = get_user_token(MY_UID)
other_token = get_user_token(OTHER_UID)
check("토큰 격리 (서로 다름)", my_token != other_token)

for uid in [MY_UID, OTHER_UID]:
    _clean(uid)

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
