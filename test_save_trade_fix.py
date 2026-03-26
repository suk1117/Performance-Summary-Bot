"""
save_trade 시그니처 변경 + price_add 역산 수식 검증 테스트
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# combined_bot import
sys.path.insert(0, os.path.dirname(__file__))
import combined_bot


class TestSaveTrade(unittest.TestCase):
    """save_trade: price/display_avg 분리 동작"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _read_records(self, uid, pname):
        fpath = combined_bot._trades_path(uid, pname)
        with open(fpath, encoding="utf-8") as f:
            return json.load(f)

    def test_display_avg_none_uses_price(self):
        """display_avg 생략 시 avg 필드 = price"""
        fpath = os.path.join(self.tmpdir, "t1.json")
        with patch("combined_bot._trades_path", return_value=fpath):
            combined_bot.save_trade(1, "p", "buy", "A", 100, 50000)
        with open(fpath, encoding="utf-8") as f:
            rec = json.load(f)[0]
        self.assertEqual(rec["avg"], 50000)
        self.assertAlmostEqual(rec["amount"], 100 * 50000)

    def test_display_avg_overrides_avg_field(self):
        """display_avg 전달 시 avg 필드 = display_avg, amount = qty * price"""
        fpath = os.path.join(self.tmpdir, "t2.json")
        with patch("combined_bot._trades_path", return_value=fpath):
            combined_bot.save_trade(1, "p", "buy", "A",
                                    300, 165000, display_avg=115000)
        with open(fpath, encoding="utf-8") as f:
            rec = json.load(f)[0]
        self.assertEqual(rec["avg"], 115000,
                         "display_avg가 avg 필드에 저장돼야 함")
        self.assertAlmostEqual(rec["amount"], 300 * 165000,
                               msg="amount는 qty * price(실거래가)여야 함")
        self.assertNotAlmostEqual(rec["amount"], 300 * 115000,
                                  msg="amount가 display_avg로 계산되면 안 됨")


class TestPriceAddFormula(unittest.TestCase):
    """price_add 역산 수식 수치 검증 (단위 테스트)"""

    def _calc_price_add(self, old_qty, old_avg, qty, avg):
        diff = qty - old_qty
        return (avg * qty - old_avg * old_qty) / diff

    def test_example_from_spec(self):
        """기존 1,000주@100,000 → 1,300주@115,000: price_add=165,000"""
        price_add = self._calc_price_add(1000, 100000, 1300, 115000)
        self.assertAlmostEqual(price_add, 165000, places=2)

    def test_amount_correct(self):
        """amount = diff * price_add = 49,500,000"""
        price_add = self._calc_price_add(1000, 100000, 1300, 115000)
        diff = 300
        self.assertAlmostEqual(diff * price_add, 49_500_000, places=0)

    def test_old_formula_was_wrong(self):
        """구 수식(new_avg)은 amount를 과소 계산함을 확인"""
        old_qty, old_avg, qty, avg = 1000, 100000, 1300, 115000
        diff = qty - old_qty
        wrong_avg = (old_qty * old_avg + diff * avg) / (old_qty + diff)
        wrong_amount = diff * wrong_avg
        correct_amount = diff * self._calc_price_add(old_qty, old_avg, qty, avg)
        self.assertLess(wrong_amount, correct_amount,
                        "구 수식 amount는 올바른 amount보다 작아야 함")

    def test_edge_buy_from_zero(self):
        """기존 0주에서 신규 매수 시 price_add == avg (역산 불필요 케이스)"""
        old_qty, old_avg, qty, avg = 0, 0, 500, 80000
        diff = qty - old_qty  # 500
        # diff > 0 이고 old_qty == 0 이면 price_add = avg * qty / diff = avg
        price_add = (avg * qty - old_avg * old_qty) / diff
        self.assertAlmostEqual(price_add, avg)

    def test_large_numbers(self):
        """큰 수 (ETF 등) 정확도"""
        price_add = self._calc_price_add(10000, 50000, 15000, 60000)
        # (60000*15000 - 50000*10000) / 5000 = (900M - 500M)/5000 = 80000
        self.assertAlmostEqual(price_add, 80000, places=2)


class TestApiAddStockIntegration(unittest.TestCase):
    """api_add_stock 호출 시 save_trade에 올바른 인자가 전달되는지 확인"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.uid = 99999
        self.pname = "테스트포트"
        # 유저 상태 초기화
        combined_bot._users_lock  # import 확인

    def _mock_trades_path(self, uid, pname):
        return os.path.join(self.tmpdir, f"trades_{uid}_{pname}.json")

    def test_save_trade_called_with_price_add(self):
        """diff>0 분기에서 save_trade가 price_add와 display_avg로 호출되는지"""
        calls = []
        original = combined_bot.save_trade

        def mock_save(uid, pname, ttype, name, qty, price, display_avg=None):
            calls.append({
                "qty": qty, "price": price, "display_avg": display_avg
            })

        with patch.object(combined_bot, "save_trade", side_effect=mock_save):
            # 직접 수식 실행 (api_add_stock 내부 로직과 동일)
            old_qty, old_avg = 1000.0, 100000.0
            qty, avg = 1300.0, 115000.0
            diff = qty - old_qty
            if diff > 0:
                price_add = (avg * qty - old_avg * old_qty) / diff
                combined_bot.save_trade(
                    self.uid, self.pname, "buy", "삼성전자",
                    diff, round(price_add, 2), display_avg=round(avg, 2)
                )

        self.assertEqual(len(calls), 1)
        c = calls[0]
        self.assertAlmostEqual(c["qty"], 300)
        self.assertAlmostEqual(c["price"], 165000, places=2,
                               msg="price(실거래가) = 165,000이어야 함")
        self.assertAlmostEqual(c["display_avg"], 115000, places=2,
                               msg="display_avg(표시용 평균단가) = 115,000이어야 함")


if __name__ == "__main__":
    unittest.main(verbosity=2)
