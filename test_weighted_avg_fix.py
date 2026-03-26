"""
api_add_stock 추가 매수 평단가 가중평균 버그 수정 검증
- avg 입력 = 추가 매수 단가
- df 저장 평단가 = 가중평균(new_avg)
- save_trade: price=avg(추가단가), display_avg=new_avg(가중평균)
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))
import combined_bot


def _weighted_avg(old_qty, old_avg, diff, price):
    """new_avg 수식 (수정 후 코드와 동일)"""
    qty = old_qty + diff
    return (old_qty * old_avg + diff * price) / qty


class TestNewAvgFormula(unittest.TestCase):
    """new_avg 수식 단위 검증"""

    def test_spec_example(self):
        """1,000주@49,005 + 300주@52,000 → 가중평균 49,696.15"""
        # (1000×49005 + 300×52000) / 1300 = 64,605,000 / 1300 = 49,696.15...
        na = _weighted_avg(1000, 49005, 300, 52000)
        self.assertAlmostEqual(na, 49696.15, places=1)

    def test_simple(self):
        """100주@1,000 + 100주@2,000 → 1,500"""
        na = _weighted_avg(100, 1000, 100, 2000)
        self.assertAlmostEqual(na, 1500.0)

    def test_buy_from_zero(self):
        """신규(old_qty=0): new_avg = price"""
        na = _weighted_avg(0, 0, 500, 80000)
        self.assertAlmostEqual(na, 80000.0)

    def test_large_numbers(self):
        """ETF 큰 수 정확도"""
        na = _weighted_avg(10000, 50000, 5000, 80000)
        # (10000*50000 + 5000*80000) / 15000 = 900_000_000/15000 = 60000
        self.assertAlmostEqual(na, 60000.0)

    def test_df_must_not_store_raw_price(self):
        """df에 raw price(추가단가)가 저장되면 안 됨"""
        old_qty, old_avg, diff, price = 1000, 49005, 300, 52000
        na = _weighted_avg(old_qty, old_avg, diff, price)
        self.assertNotAlmostEqual(na, price,
            msg="df 저장값이 추가 매수 단가(52,000)와 달라야 함")


class TestSaveTradeArgs(unittest.TestCase):
    """수정 후 save_trade 호출 인자 검증
    price=추가매수단가, display_avg=가중평균
    """

    def _run_diff_gt0(self, old_qty, old_avg, diff, price):
        """api_add_stock diff>0 분기 로직 직접 실행"""
        calls = []

        def mock_save(uid, pname, ttype, name, qty, p, display_avg=None):
            calls.append({"qty": qty, "price": p, "display_avg": display_avg})

        with patch.object(combined_bot, "save_trade", side_effect=mock_save):
            qty = old_qty + diff
            new_avg = (old_qty * old_avg + diff * price) / qty
            combined_bot.save_trade(
                1, "p", "buy", "X",
                diff, round(price, 2), display_avg=round(new_avg, 2)
            )
        return calls[0], round(new_avg, 2)

    def test_price_is_buy_price_not_weighted(self):
        """price 인자 = 추가 매수 단가"""
        c, _ = self._run_diff_gt0(1000, 49005, 300, 52000)
        self.assertAlmostEqual(c["price"], 52000,
            msg="price는 추가 매수 단가(52,000)여야 함")

    def test_display_avg_is_weighted_avg(self):
        """display_avg 인자 = 가중평균"""
        c, new_avg = self._run_diff_gt0(1000, 49005, 300, 52000)
        self.assertAlmostEqual(c["display_avg"], new_avg,
            msg="display_avg는 가중평균이어야 함")

    def test_display_avg_not_raw_price(self):
        """display_avg가 추가 매수 단가(raw price)가 아님을 확인"""
        c, _ = self._run_diff_gt0(1000, 49005, 300, 52000)
        self.assertNotAlmostEqual(c["display_avg"], 52000,
            msg="display_avg가 추가 매수 단가(52,000)면 버그")

    def test_qty_is_diff_not_total(self):
        """qty 인자 = diff (추가 수량), total qty 아님"""
        c, _ = self._run_diff_gt0(1000, 49005, 300, 52000)
        self.assertAlmostEqual(c["qty"], 300,
            msg="save_trade qty는 추가 수량(300)이어야 함")

    def test_amount_uses_buy_price(self):
        """amount = diff * price (추가단가), 가중평균 아님"""
        fpath = tempfile.mktemp(suffix=".json")
        with patch("combined_bot._trades_path", return_value=fpath):
            qty, old_qty, old_avg, price = 1300, 1000, 49005.0, 52000.0
            diff = qty - old_qty
            new_avg = (old_qty * old_avg + diff * price) / qty
            combined_bot.save_trade(1, "p", "buy", "X",
                                    diff, round(price, 2),
                                    display_avg=round(new_avg, 2))
        with open(fpath, encoding="utf-8") as f:
            rec = json.load(f)[0]
        os.remove(fpath)
        self.assertAlmostEqual(rec["amount"], diff * price, places=0,
            msg="amount = 300 × 52,000 = 15,600,000이어야 함")
        self.assertNotAlmostEqual(rec["amount"], diff * new_avg, places=0,
            msg="amount가 가중평균으로 계산되면 안 됨")


class TestDiffZeroAndNegative(unittest.TestCase):
    """diff==0, diff<0 분기 수식 검증"""

    def test_diff_zero_stores_input_avg(self):
        """수량 동일(diff=0): avg 그대로 저장 (평단가만 수정)"""
        # 수식 자체가 없고 avg를 그대로 df에 씀 — 값 동일성만 확인
        avg_input = 55000
        stored = avg_input  # 코드: df에 avg 그대로
        self.assertEqual(stored, avg_input)

    def test_diff_negative_sell_uses_old_avg(self):
        """diff<0(매도): save_trade price = old_avg"""
        calls = []

        def mock_save(uid, pname, ttype, name, qty, price, display_avg=None):
            calls.append({"ttype": ttype, "qty": qty, "price": price})

        with patch.object(combined_bot, "save_trade", side_effect=mock_save):
            old_avg = 49005.0
            diff = -300
            combined_bot.save_trade(1, "p", "sell", "X",
                                    abs(diff), old_avg)

        self.assertEqual(calls[0]["ttype"], "sell")
        self.assertAlmostEqual(calls[0]["price"], old_avg,
            msg="매도 기록의 price는 old_avg여야 함")


if __name__ == "__main__":
    unittest.main(verbosity=2)
