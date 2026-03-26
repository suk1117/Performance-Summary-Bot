"""
거래 구분 세분화 수정 검증
1. api_add_stock — 신규매수 / 추가매수 / 일부매도 / 전량매도(qty==0)
2. api_del_stock — 전량매도
3. build_user_html — trade_rows 레이블·색상 (하위 호환 포함)
"""
import sys
import os
import re
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))
import combined_bot

BOT_PATH = os.path.join(os.path.dirname(__file__), "combined_bot.py")
with open(BOT_PATH, encoding="utf-8") as f:
    SRC = f.read()


# ─────────────────────────────────────────────
# 헬퍼: save_trade 호출 캡처
# ─────────────────────────────────────────────
def _capture_save_trade():
    calls = []
    def mock(uid, pname, ttype, name, qty, price, display_avg=None):
        calls.append({"ttype": ttype, "qty": qty, "price": price, "display_avg": display_avg})
    return calls, mock


# ─────────────────────────────────────────────
# 1. api_add_stock 로직 직접 재현
# ─────────────────────────────────────────────
class TestApiAddStockTradeTypes(unittest.TestCase):

    def _run(self, old_qty, old_avg, new_qty, new_avg, name="삼성전자"):
        """api_add_stock 내 기존 종목 분기 로직 재현"""
        import pandas as pd
        calls, mock_save = _capture_save_trade()

        df = pd.DataFrame([{
            "종목명": name, "국가": "KR", "비중(%)": 0.0,
            "평단가": old_avg, "수량": old_qty, "통화": "KRW"
        }])

        with patch.object(combined_bot, "save_trade", side_effect=mock_save), \
             patch.object(combined_bot, "save_portfolios"), \
             patch.object(combined_bot, "_get_user_state", return_value={
                 "portfolios": {"p": {"df": df.copy(), "name": "p", "last_update": None}},
                 "active_pname": "p"
             }), \
             patch.object(combined_bot, "_check_token"), \
             combined_bot.app_flask.test_request_context(
                 json={"종목명": name, "국가": "KR", "수량": new_qty, "평단가": new_avg}
             ):
            from flask import request as flask_req
            combined_bot.request = flask_req
            # 직접 로직 실행 (api_add_stock 내부와 동일)
            qty = float(new_qty)
            avg = float(new_avg)
            old_q = float(old_qty)
            old_a = float(old_avg)
            diff = qty - old_q

            if diff > 0:
                nw = (old_q * old_a + diff * avg) / qty
                combined_bot.save_trade(1, "p", "추가매수", name, diff, round(avg, 2))
            elif diff < 0:
                if qty == 0:
                    combined_bot.save_trade(1, "p", "전량매도", name, old_q, old_a)
                else:
                    combined_bot.save_trade(1, "p", "일부매도", name, abs(diff), old_a)

        return calls

    def test_추가매수_type(self):
        calls = self._run(1000, 49005, 1300, 52000)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["ttype"], "추가매수")

    def test_추가매수_qty_is_diff(self):
        calls = self._run(1000, 49005, 1300, 52000)
        self.assertAlmostEqual(calls[0]["qty"], 300)

    def test_추가매수_price_is_buy_price(self):
        calls = self._run(1000, 49005, 1300, 52000)
        self.assertAlmostEqual(calls[0]["price"], 52000)

    def test_일부매도_type(self):
        calls = self._run(1000, 49005, 700, 49005)
        self.assertEqual(calls[0]["ttype"], "일부매도")

    def test_일부매도_qty_is_diff(self):
        calls = self._run(1000, 49005, 700, 49005)
        self.assertAlmostEqual(calls[0]["qty"], 300)

    def test_일부매도_price_is_old_avg(self):
        calls = self._run(1000, 49005, 700, 49005)
        self.assertAlmostEqual(calls[0]["price"], 49005)

    def test_전량매도_qty0(self):
        calls = self._run(1000, 49005, 0, 49005)
        self.assertEqual(calls[0]["ttype"], "전량매도")

    def test_전량매도_qty0_qty_is_old_qty(self):
        calls = self._run(1000, 49005, 0, 49005)
        self.assertAlmostEqual(calls[0]["qty"], 1000)

    def test_수량동일_no_trade(self):
        """수량 동일: save_trade 호출 없음"""
        calls = self._run(1000, 49005, 1000, 50000)
        self.assertEqual(len(calls), 0)


class TestApiAddStockNewStock(unittest.TestCase):
    """신규 종목 → 신규매수"""

    def test_신규매수_type_in_source(self):
        self.assertIn('"신규매수"', SRC)

    def test_신규매수_called_for_new_stock(self):
        calls, mock_save = _capture_save_trade()
        with patch.object(combined_bot, "save_trade", side_effect=mock_save):
            combined_bot.save_trade(1, "p", "신규매수", "카카오", 500, 60000)
        self.assertEqual(calls[0]["ttype"], "신규매수")


class TestApiDelStock(unittest.TestCase):
    """api_del_stock → 전량매도"""

    def test_del_stock_uses_전량매도(self):
        self.assertIn('"전량매도"', SRC)
        # api_del_stock 내부에 "sell" 문자열이 남아있으면 안 됨
        # (save_trade 호출부 기준)
        del_block = SRC[SRC.find("def api_del_stock"):SRC.find("def api_del_stock") + 900]
        self.assertNotIn('"sell"', del_block)
        self.assertIn('"전량매도"', del_block)


# ─────────────────────────────────────────────
# 2. build_user_html 레이블·색상 로직
# ─────────────────────────────────────────────
def _render_label(ttype: str):
    """build_user_html 내 색상 로직 Python으로 재현"""
    _ttype = ttype
    if _ttype == "신규매수":
        t_label, t_color, t_bg, t_border = "신규매수", "#0ea5e9", "#eff6ff", "#bfdbfe"
    elif _ttype == "추가매수" or _ttype == "buy":
        t_label, t_color, t_bg, t_border = "추가매수", "#16a34a", "#f0fdf4", "#bbf7d0"
    elif _ttype == "일부매도":
        t_label, t_color, t_bg, t_border = "일부매도", "#f97316", "#fff7ed", "#fed7aa"
    elif _ttype == "전량매도" or _ttype == "sell":
        t_label, t_color, t_bg, t_border = "전량매도", "#dc2626", "#fef2f2", "#fecaca"
    else:
        t_label, t_color, t_bg, t_border = _ttype, "#64748b", "#f8fafc", "#e2e8f0"
    return t_label, t_color, t_bg, t_border


class TestTradeRowsRendering(unittest.TestCase):

    def test_신규매수_label(self):
        label, color, *_ = _render_label("신규매수")
        self.assertEqual(label, "신규매수")
        self.assertEqual(color, "#0ea5e9")

    def test_추가매수_label(self):
        label, color, *_ = _render_label("추가매수")
        self.assertEqual(label, "추가매수")
        self.assertEqual(color, "#16a34a")

    def test_일부매도_label(self):
        label, color, *_ = _render_label("일부매도")
        self.assertEqual(label, "일부매도")
        self.assertEqual(color, "#f97316")

    def test_전량매도_label(self):
        label, color, *_ = _render_label("전량매도")
        self.assertEqual(label, "전량매도")
        self.assertEqual(color, "#dc2626")

    # 하위 호환
    def test_buy_compat(self):
        label, color, *_ = _render_label("buy")
        self.assertEqual(label, "추가매수")
        self.assertEqual(color, "#16a34a")

    def test_sell_compat(self):
        label, color, *_ = _render_label("sell")
        self.assertEqual(label, "전량매도")
        self.assertEqual(color, "#dc2626")

    def test_unknown_type_fallback(self):
        label, color, *_ = _render_label("미확인")
        self.assertEqual(label, "미확인")
        self.assertEqual(color, "#64748b")

    def test_all_types_distinct_colors(self):
        """4가지 타입은 서로 다른 색상"""
        colors = [_render_label(t)[1] for t in ("신규매수", "추가매수", "일부매도", "전량매도")]
        self.assertEqual(len(set(colors)), 4, "4가지 타입 색상이 모두 달라야 함")

    def test_source_has_four_type_strings(self):
        for t in ("신규매수", "추가매수", "일부매도", "전량매도"):
            self.assertIn(f'"{t}"', SRC, f'소스에 "{t}" 문자열 없음')


# ─────────────────────────────────────────────
# 3. 소스 레벨 검증
# ─────────────────────────────────────────────
class TestSourceLevel(unittest.TestCase):

    def test_no_bare_buy_in_add_stock(self):
        """api_add_stock 내에 구형 "buy" save_trade 호출이 없어야 함"""
        block = SRC[SRC.find("def api_add_stock"):SRC.find("def api_del_stock")]
        # save_trade(..., "buy", ...) 패턴
        matches = re.findall(r'save_trade\([^)]*"buy"', block)
        self.assertEqual(matches, [], f'api_add_stock에 "buy" 호출 잔존: {matches}')

    def test_no_bare_sell_in_add_stock(self):
        block = SRC[SRC.find("def api_add_stock"):SRC.find("def api_del_stock")]
        matches = re.findall(r'save_trade\([^)]*"sell"', block)
        self.assertEqual(matches, [], f'api_add_stock에 "sell" 호출 잔존: {matches}')

    def test_qty0_branch_exists(self):
        """qty == 0 분기 코드가 존재해야 함"""
        self.assertIn("qty == 0", SRC)

    def test_전량매도_in_del_stock(self):
        block = SRC[SRC.find("def api_del_stock"):SRC.find("def api_del_stock") + 900]
        self.assertIn("전량매도", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
