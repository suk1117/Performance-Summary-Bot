from __future__ import annotations
import json
import os
import tempfile
import secrets as _secrets
from datetime import datetime

import pandas as pd

from portfolio_bot.config import DATA_DIR
from portfolio_bot.state import (
    _get_portfolios_file_lock,
    _cashflow_locks, _cashflow_locks_lock,
    _history_locks, _history_locks_lock,
    _trades_locks, _trades_locks_lock,
)

_NUMERIC_COLS = ["비중(%)", "평단가", "수량", "현재가", "수익률(%)", "등락률(%)", "USD_KRW"]
_EMPTY_COLS   = ["종목명", "국가", "비중(%)", "평단가", "수량", "통화"]
_DERIVED_COLS = ["현재가", "수익률(%)", "등락률(%)", "USD_KRW"]


# ─── 내부 헬퍼 ────────────────────────────────────────
def _safe_pname(pname: str) -> str:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]+", pname):
        raise ValueError(f"잘못된 포트폴리오 ID: {pname!r}")
    return pname

def _user_dir(uid: int) -> str:
    """data/user_{uid}/ 생성 후 경로 반환"""
    path = os.path.join(DATA_DIR, f"user_{uid}")
    os.makedirs(path, exist_ok=True)
    return path

def _portfolios_file(uid: int) -> str:
    return os.path.join(_user_dir(uid), "portfolios.json")

def _raw_unsafe(uid: int) -> dict:
    """락 없이 파일만 읽음 — 이미 락을 잡은 상태에서 호출하는 내부 헬퍼용."""
    fpath = _portfolios_file(uid)
    if not os.path.exists(fpath):
        return {"active": "", "next_id": 1, "items": {}}
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active": "", "next_id": 1, "items": {}}

def _raw(uid: int) -> dict:
    lock = _get_portfolios_file_lock(uid)
    with lock:
        return _raw_unsafe(uid)

def _save_raw(uid: int, data: dict):
    fpath = _portfolios_file(uid)
    dirpath = os.path.dirname(fpath)
    os.makedirs(dirpath, exist_ok=True)
    lock = _get_portfolios_file_lock(uid)
    with lock:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                         dir=dirpath, delete=False, suffix=".tmp") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            tmp_path = f.name
        os.replace(tmp_path, fpath)

def _df_from_records(records: list) -> pd.DataFrame:
    df = pd.DataFrame(records) if records else pd.DataFrame(columns=_EMPTY_COLS)
    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ─── 토큰 관리 ────────────────────────────────────────
def get_user_token(uid: int) -> str:
    """uid별 URL 토큰 반환. 없으면 생성 후 저장."""
    fpath = _portfolios_file(uid)
    lock  = _get_portfolios_file_lock(uid)
    with lock:
        raw   = _raw_unsafe(uid)
        token = raw.get("token", "")
        if not token:
            token = _secrets.token_urlsafe(16)
            raw["token"] = token
            dirpath = os.path.dirname(fpath)
            os.makedirs(dirpath, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                              dir=dirpath, delete=False, suffix=".tmp") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2, default=str)
                tmp_path = f.name
            os.replace(tmp_path, fpath)
    return token


# ─── 구버전 마이그레이션 ──────────────────────────────
def _migrate(uid: int, owner_uid: int):
    """기존 data/portfolio.json → data/user_{uid}/portfolios.json"""
    dst = _portfolios_file(uid)
    if os.path.exists(dst):
        return
    import shutil
    # 단일 포트폴리오 구버전
    if uid == owner_uid:
        old_file = os.path.join(DATA_DIR, "portfolio.json")
        if not os.path.exists(old_file):
            return
        try:
            with open(old_file, "r", encoding="utf-8") as f:
                old = json.load(f)
            pname = "p1"
            raw = {
                "active":  pname,
                "next_id": 2,
                "items": {
                    pname: {
                        "name":        old.get("name", "기본 포트폴리오"),
                        "last_update": old.get("last_update"),
                        "df":          old.get("df", []),
                    }
                },
            }
            _save_raw(uid, raw)
            for old_name, new_name in [
                ("cashflow.json", f"cashflow_{pname}.json"),
                ("history.json",  f"history_{pname}.json"),
            ]:
                src = os.path.join(DATA_DIR, old_name)
                d   = os.path.join(_user_dir(uid), new_name)
                if os.path.exists(src) and not os.path.exists(d):
                    shutil.copy2(src, d)
            print(f"✅ portfolio.json → data/user_{uid}/ 마이그레이션 완료")
        except Exception as e:
            print(f"⚠️  마이그레이션 오류: {e}")


# ─── 포트폴리오 로드/저장 ─────────────────────────────
def load_portfolios(uid: int) -> tuple[dict, str]:
    _migrate(uid, uid)
    raw = _raw(uid)
    items = {}
    for pname, p in raw.get("items", {}).items():
        last_update = None
        if p.get("last_update"):
            try:
                last_update = datetime.fromisoformat(p["last_update"])
            except Exception:
                pass
        items[pname] = {
            "name":        p.get("name", pname),
            "last_update": last_update,
            "df":          _df_from_records(p.get("df", [])),
        }
    if not items:
        pname = "p1"
        items[pname] = {
            "name":        "기본 포트폴리오",
            "last_update": None,
            "df":          pd.DataFrame(columns=_EMPTY_COLS),
        }
        raw["active"]  = pname
        raw["next_id"] = 2
        raw["items"]   = {"p1": {"name": "기본 포트폴리오", "last_update": None, "df": []}}
        _save_raw(uid, raw)
    active = raw.get("active", "")
    if active not in items:
        active = next(iter(items))
    return items, active


def save_portfolios(uid: int, portfolios: dict, active_pname: str):
    fpath   = _portfolios_file(uid)
    dirpath = os.path.dirname(fpath)
    lock    = _get_portfolios_file_lock(uid)
    with lock:
        # 최신 디스크 상태 읽기 (next_id, token 등 보존)
        raw = _raw_unsafe(uid)
        raw["active"] = active_pname
        out = {}
        for pname, p in portfolios.items():
            df = p.get("df")
            if df is not None:
                df_save = df.drop(columns=[c for c in _DERIVED_COLS if c in df.columns])
                records = df_save.to_dict(orient="records")
            else:
                records = []
            out[pname] = {
                "name":        p.get("name", pname),
                "last_update": p["last_update"].isoformat() if p.get("last_update") else None,
                "df":          records,
            }
        raw["items"] = out
        os.makedirs(dirpath, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                          dir=dirpath, delete=False, suffix=".tmp") as tf:
            json.dump(raw, tf, ensure_ascii=False, indent=2, default=str)
            tmp_path = tf.name
        os.replace(tmp_path, fpath)


def create_portfolio(uid: int, name: str) -> str:
    """pname을 생성해 반환. 실제 저장은 호출자가 save_portfolios로 처리."""
    fpath = _portfolios_file(uid)
    lock  = _get_portfolios_file_lock(uid)
    with lock:
        raw = _raw_unsafe(uid)
        next_id = raw.get("next_id", 1)
        pname   = f"p{next_id}"
        raw["next_id"] = next_id + 1
        dirpath = os.path.dirname(fpath)
        os.makedirs(dirpath, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                          dir=dirpath, delete=False, suffix=".tmp") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2, default=str)
            tmp_path = f.name
        os.replace(tmp_path, fpath)
    return pname


def delete_portfolio(uid: int, pname: str):
    """history·cashflow 파일만 삭제. items 저장은 호출자가 save_portfolios로 처리."""
    # 지연 import — circular import 방지
    from portfolio_bot.storage.history import _history_path
    from portfolio_bot.storage.cashflow import _cashflow_path
    from portfolio_bot.storage.trades import _trades_path
    for path in [_history_path(uid, pname), _cashflow_path(uid, pname), _trades_path(uid, pname)]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
    # cashflow 락 정리
    key = (uid, pname)
    with _cashflow_locks_lock:
        _cashflow_locks.pop(key, None)
    # history 락 정리
    with _history_locks_lock:
        _history_locks.pop(key, None)
    # trades 락 정리
    with _trades_locks_lock:
        _trades_locks.pop(key, None)
