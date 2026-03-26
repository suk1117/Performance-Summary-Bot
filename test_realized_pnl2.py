"""
실현 손익 자동 계산 리팩토링 검증
1. save_trade — 매도 시 realized_pnl 자동 계산
2. compute_realized_pnl — realized_pnl 직접 읽기
3. api_add_stock — 매도 분기 price/display_avg 전달
4. 소스 레벨 검증
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
import combined_bot

BOT_PATH = os.path.join(os.path.dirname(__file__), "combined_bot.py")
with open(BOT_PATH, encoding="utf-8") as f:
    SRC = f.read()


def _write_trade(**kwargs):
    fpath = tempfile.mktemp(suffix=".json")
    with patch("combined_bot._trades_path", return_value=fpath):
        combined_bot.save_trade(1, "p", **kwargs)
    with open(fpath, encoding="utf-8") as f:
        rec = json.load(f)[0]
    os.remove(fpath)
    return rec


# ─────────────────────────────────────────────
# 1. save_trade 자동 계산
# ─────────────────────────────────────────────
class TestSaveTradeAutoCalc(unittest.TestCase):

    def test_buy_no_realized_pnl(self):
        rec = _write_trade(trade_type="신규매수", name="A", qty=100, price=50000)
        self.assertNotIn("realized_pnl", rec)

    def test_sell_without_display_avg_no_realized(self):
        """display_avg 없는 매도 → realized_pnl 없음"""
        rec = _write_trade(trade_type="일부매도", name="A", qty=100, price=55000)
        self.assertNotIn("realized_pnl", rec)

    def test_sell_with_display_avg_auto_calc(self):
        """price=매도단가, display_avg=매수평단가 → 자동 계산"""
        rec = _write_trade(trade_type="일부매도", name="A", qty=100,
                           price=55000, display_avg=49000)
        self.assertAlmostEqual(rec["realized_pnl"], 100 * (55000 - 49000))

    def test_full_sell_realized_pnl(self):
        rec = _write_trade(trade_type="전량매도", name="A", qty=500,
                           price=52000, display_avg=49000)
        self.assertAlmostEqual(rec["realized_pnl"], 500 * (52000 - 49000))

    def test_loss_realized_pnl_negative(self):
        rec = _write_trade(trade_type="일부매도", name="A", qty=100,
                           price=45000, display_avg=49000)
        self.assertAlmostEqual(rec["realized_pnl"], 100 * (45000 - 49000))

    def test_legacy_sell_type_also_works(self):
        """하위 호환: "sell" 타입도 자동 계산"""
        rec = _write_trade(trade_type="sell", name="A", qty=100,
                           price=55000, display_avg=49000)
        self.assertAlmostEqual(rec["realized_pnl"], 100 * (55000 - 49000))

    def test_avg_field_is_display_avg(self):
        """avg 필드 = display_avg (매수 평단가로 표시)"""
        rec = _write_trade(trade_type="일부매도", name="A", qty=100,
                           price=55000, display_avg=49000)
        self.assertEqual(rec["avg"], 49000)

    def test_amount_is_qty_times_sell_price(self):
        """amount = qty × price (매도단가)"""
        rec = _write_trade(trade_type="일부매도", name="A", qty=100,
                           price=55000, display_avg=49000)
        self.assertAlmostEqual(rec["amount"], 100 * 55000)

    def test_no_sell_price_param(self):
        """sell_price 파라미터가 없어야 함 (소스 확인)"""
        import inspect
        sig = str(inspect.signature(combined_bot.save_trade))
        self.assertNotIn("sell_price", sig)


# ─────────────────────────────────────────────
# 2. compute_realized_pnl — realized_pnl 직접 읽기
# ─────────────────────────────────────────────
class TestComputeRealizedPnlV2(unittest.TestCase):

    def _run(self, trades):
        with patch("combined_bot.load_trades", return_value=trades):
            return combined_bot.compute_realized_pnl(1, "p")

    def test_no_realized_pnl_field_skipped(self):
        total, _ = self._run([
            {"type": "일부매도", "name": "A", "qty": 100, "avg": 49000, "amount": 0}
        ])
        self.assertEqual(total, 0.0)

    def test_realized_pnl_field_counted(self):
        total, per = self._run([
            {"type": "일부매도", "name": "A", "qty": 100, "avg": 49000,
             "amount": 0, "realized_pnl": 600000}
        ])
        self.assertAlmostEqual(total, 600000)
        self.assertAlmostEqual(per["A"], 600000)

    def test_loss_negative_total(self):
        total, _ = self._run([
            {"type": "전량매도", "name": "B", "qty": 200, "avg": 50000,
             "amount": 0, "realized_pnl": -400000}
        ])
        self.assertAlmostEqual(total, -400000)

    def test_multiple_stocks_aggregated(self):
        total, per = self._run([
            {"type": "일부매도", "name": "A", "qty": 100,
             "amount": 0, "realized_pnl": 600000},
            {"type": "전량매도", "name": "B", "qty": 200,
             "amount": 0, "realized_pnl": -400000},
        ])
        self.assertAlmostEqual(total, 200000)
        self.assertAlmostEqual(per["A"], 600000)
        self.assertAlmostEqual(per["B"], -400000)

    def test_buy_trades_ignored(self):
        total, _ = self._run([
            {"type": "신규매수", "name": "A", "qty": 100,
             "amount": 0, "realized_pnl": 999999}
        ])
        self.assertEqual(total, 0.0)

    def test_no_sell_price_dependency(self):
        """sell_price 필드 없어도 realized_pnl 있으면 집계"""
        total, _ = self._run([
            {"type": "일부매도", "name": "A", "qty": 100,
             "amount": 0, "realized_pnl": 500000}
            # sell_price 키 없음
        ])
        self.assertAlmostEqual(total, 500000)


# ─────────────────────────────────────────────
# 3. api_add_stock 매도 분기 로직 재현
# ─────────────────────────────────────────────
class TestApiAddStockSellRefactor(unittest.TestCase):

    def _run(self, old_qty, old_avg, new_qty, sell_price_input):
        calls = []
        def mock_save(uid, pname, ttype, name, qty, price, display_avg=None):
            calls.append({"ttype": ttype, "qty": qty, "price": price,
                          "display_avg": display_avg})
        with patch.object(combined_bot, "save_trade", side_effect=mock_save):
            qty   = float(new_qty)
            avg   = float(sell_price_input)   # avg = 매도 단가 입력
            old_q = float(old_qty)
            old_a = float(old_avg)
            diff  = qty - old_q
            if diff < 0:
                if qty == 0:
                    combined_bot.save_trade(1, "p", "전량매도", "X", old_q,
                                            round(avg, 2), display_avg=round(old_a, 2))
                else:
                    combined_bot.save_trade(1, "p", "일부매도", "X", abs(diff),
                                            round(avg, 2), display_avg=round(old_a, 2))
        return calls

    def test_partial_sell_price_is_sell_price(self):
        calls = self._run(1000, 49000, 700, 55000)
        self.assertAlmostEqual(calls[0]["price"], 55000,
                               msg="price = 매도 단가")

    def test_partial_sell_display_avg_is_old_avg(self):
        calls = self._run(1000, 49000, 700, 55000)
        self.assertAlmostEqual(calls[0]["display_avg"], 49000,
                               msg="display_avg = 기존 매수 평단가")

    def test_partial_sell_qty_is_diff(self):
        calls = self._run(1000, 49000, 700, 55000)
        self.assertAlmostEqual(calls[0]["qty"], 300)

    def test_full_sell_price_is_sell_price(self):
        calls = self._run(1000, 49000, 0, 52000)
        self.assertEqual(calls[0]["ttype"], "전량매도")
        self.assertAlmostEqual(calls[0]["price"], 52000)

    def test_full_sell_display_avg_is_old_avg(self):
        calls = self._run(1000, 49000, 0, 52000)
        self.assertAlmostEqual(calls[0]["display_avg"], 49000)

    def test_realized_pnl_auto_from_save_trade(self):
        """save_trade 실제 호출 시 realized_pnl 자동 계산 확인"""
        fpath = tempfile.mktemp(suffix=".json")
        with patch("combined_bot._trades_path", return_value=fpath):
            combined_bot.save_trade(1, "p", "일부매도", "X", 300,
                                    55000.0, display_avg=49000.0)
        with open(fpath, encoding="utf-8") as f:
            rec = json.load(f)[0]
        os.remove(fpath)
        self.assertAlmostEqual(rec["realized_pnl"], 300 * (55000 - 49000))


# ─────────────────────────────────────────────
# 4. 소스 레벨 검증
# ─────────────────────────────────────────────
class TestSourceLevelV2(unittest.TestCase):

    def test_no_sell_price_param_in_save_trade(self):
        block = SRC[SRC.find("def save_trade"):SRC.find("def save_trade") + 200]
        self.assertNotIn("sell_price", block)

    def test_sell_types_tuple_in_save_trade(self):
        self.assertIn('_sell_types = ("일부매도", "전량매도", "sell")', SRC)

    def test_no_sell_price_raw_in_api_add_stock(self):
        block = SRC[SRC.find("def api_add_stock"):SRC.find("def api_del_stock")]
        self.assertNotIn("sell_price_raw", block)
        self.assertNotIn("sell_price", block)

    def test_no_row_sell_price_html(self):
        self.assertNotIn('id="row-sell-price"', SRC)

    def test_no_f_sell_price_html(self):
        self.assertNotIn('id="f-sell-price"', SRC)

    def test_on_qty_change_uses_label_avg(self):
        block = SRC[SRC.find("function _onQtyChange"):SRC.find("function _onQtyChange") + 500]
        self.assertIn("label-avg", block)
        self.assertIn("매도 단가", block)

    def test_no_sell_price_in_payload(self):
        block = SRC[SRC.find("async function saveStock"):SRC.find("async function saveStock") + 700]
        self.assertNotIn("매도단가", block)
        self.assertNotIn("_sellPrice", block)

    def test_open_add_modal_resets_label(self):
        block = SRC[SRC.find("function openAddModal"):SRC.find("function openAddModal") + 800]
        self.assertIn("label-avg", block)

    def test_open_edit_modal_no_sell_price(self):
        block = SRC[SRC.find("function openEditModal"):SRC.find("function openEditModal") + 700]
        self.assertNotIn("f-sell-price", block)
        self.assertNotIn("row-sell-price", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
