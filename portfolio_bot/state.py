from __future__ import annotations
import threading

# ── 전역 상태 ──
# all_users[uid] = {"portfolios": {pname: {...}}, "active_pname": ""}
all_users:   dict             = {}
_users_lock: threading.Lock   = threading.Lock()
public_url:  str              = ""
tg_bot                        = None  # telegram.Bot | None (타입 힌트는 circular import 방지를 위해 생략)

# ── 대시보드 빌드 중복 방지 ──
_build_lock  = threading.Lock()   # _building / _hist_check 접근용
_building:   set  = set()         # (uid, pname) 튜플
_hist_check: dict = {}            # (uid, pname) -> "YYYY-MM-DD"

# ── cashflow 파일별 락 ──
_cashflow_locks: dict = {}              # {(uid, pname): threading.Lock()}
_cashflow_locks_lock = threading.Lock()  # _cashflow_locks 딕셔너리 접근용

def _get_cashflow_lock(uid: int, pname: str) -> threading.Lock:
    key = (uid, pname)
    with _cashflow_locks_lock:
        if key not in _cashflow_locks:
            _cashflow_locks[key] = threading.Lock()
        return _cashflow_locks[key]

# ── history 파일별 락 ──
_history_locks: dict = {}
_history_locks_lock = threading.Lock()

def _get_history_lock(uid: int, pname: str) -> threading.Lock:
    key = (uid, pname)
    with _history_locks_lock:
        if key not in _history_locks:
            _history_locks[key] = threading.Lock()
        return _history_locks[key]

# ── trades 파일별 락 ──
_trades_locks: dict = {}
_trades_locks_lock = threading.Lock()

def _get_trades_lock(uid: int, pname: str) -> threading.Lock:
    key = (uid, pname)
    with _trades_locks_lock:
        if key not in _trades_locks:
            _trades_locks[key] = threading.Lock()
        return _trades_locks[key]

# ── portfolios.json uid별 파일 락 ──
_portfolios_file_locks: dict = {}
_portfolios_file_locks_lock = threading.Lock()

def _get_portfolios_file_lock(uid: int) -> threading.Lock:
    with _portfolios_file_locks_lock:
        if uid not in _portfolios_file_locks:
            _portfolios_file_locks[uid] = threading.Lock()
        return _portfolios_file_locks[uid]
