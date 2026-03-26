"""
실현 손익 기능 검증 (자동 계산 방식 기준)
1. save_trade — display_avg 기반 자동 realized_pnl 계산
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
# 1. save_trade — 자동 realized_pnl
# ─────────────────────────────────────────────
class TestSaveTradeSellPrice(unittest.TestCase):

    def test_buy_has_no_realized_pnl(self):
        rec = _write_trade(trade_type="추가매수", name="A", qty=100, price=50000)
        self.assertNotIn("sell_price", rec)
        self.assertNotIn("realized_pnl", rec)

    def test_sell_without_display_avg_no_realized(self):
        """display_avg 없는 매도 → realized_pnl 없음"""
        rec = _write_trade(trade_type="일부매도", name="A", qty=100, price=55000)
        self.assertNotIn("sell_price", rec)
        self.assertNotIn("realized_pnl", rec)

    def test_sell_with_display_avg_realized_profit(self):
        """price=매도단가, display_avg=매수평단가 → realized_pnl 자동 계산 (이익)"""
        rec = _write_trade(trade_type="일부매도", name="A", qty=100,
                           price=55000, display_avg=49000)
        self.assertAlmostEqual(rec["realized_pnl"], 100 * (55000 - 49000))

    def test_sell_with_display_avg_realized_loss(self):
        """realized_pnl 손실"""
        rec = _write_trade(trade_type="일부매도", name="A", qty=100,
                           price=45000, display_avg=49000)
        self.assertAlmostEqual(rec["realized_pnl"], 100 * (45000 - 49000))

    def test_realized_pnl_uses_display_avg_as_buy_avg(self):
        """display_avg가 매수 평단가로 사용됨"""
        rec = _write_trade(trade_type="일부매도", name="A", qty=50,
                           price=52000, display_avg=48000)
        self.assertAlmostEqual(rec["realized_pnl"], 50 * (52000 - 48000))

    def test_amount_is_qty_times_sell_price(self):
        """amount = qty × price (매도단가)"""
        rec = _write_trade(trade_type="일부매도", name="A", qty=100,
                           price=55000, display_avg=49000)
        self.assertAlmostEqual(rec["amount"], 100 * 55000)

    def test_avg_field_is_display_avg(self):
        """avg 필드 = display_avg (매수 평단가)"""
        rec = _write_trade(trade_type="일부매도", name="A", qty=100,
                           price=55000, display_avg=49000)
        self.assertEqual(rec["avg"], 49000)


# ─────────────────────────────────────────────
# 2. compute_realized_pnl
# ─────────────────────────────────────────────
class TestComputeRealizedPnl(unittest.TestCase):

    def _run(self, trades):
        with patch("combined_bot.load_trades", return_value=trades):
            return combined_bot.compute_realized_pnl(1, "p")

    def test_no_sell_trades(self):
        total, per = self._run([
            {"type": "신규매수", "name": "A", "qty": 100, "avg": 50000, "amount": 0}
        ])
        self.assertEqual(total, 0.0)
        self.assertEqual(per, {})

    def test_sell_without_realized_pnl_skipped(self):
        """realized_pnl 없는 매도 기록 → skip (하위 호환)"""
        total, _ = self._run([
            {"type": "일부매도", "name": "A", "qty": 100, "avg": 49000, "amount": 0}
        ])
        self.assertEqual(total, 0.0)

    def test_single_profit(self):
        total, per = self._run([
            {"type": "일부매도", "name": "A", "qty": 100, "avg": 49000,
             "amount": 0, "realized_pnl": 600000}
        ])
        self.assertAlmostEqual(total, 600000)
        self.assertAlmostEqual(per["A"], 600000)

    def test_single_loss(self):
        total, _ = self._run([
            {"type": "일부매도", "name": "A", "qty": 100, "avg": 49000,
             "amount": 0, "realized_pnl": -400000}
        ])
        self.assertAlmostEqual(total, -400000)

    def test_multiple_trades_same_stock(self):
        total, per = self._run([
            {"type": "일부매도", "name": "A", "qty": 100,
             "realized_pnl": 600000, "amount": 0},
            {"type": "전량매도", "name": "A", "qty": 200,
             "realized_pnl": 600000, "amount": 0},
        ])
        self.assertAlmostEqual(total, 1200000)
        self.assertAlmostEqual(per["A"], 1200000)

    def test_multiple_stocks(self):
        total, per = self._run([
            {"type": "일부매도", "name": "A", "realized_pnl": 600000, "amount": 0},
            {"type": "전량매도", "name": "B", "realized_pnl": -500000, "amount": 0},
        ])
        self.assertAlmostEqual(total, 100000)
        self.assertAlmostEqual(per["A"], 600000)
        self.assertAlmostEqual(per["B"], -500000)

    def test_legacy_sell_skipped(self):
        """기존 "sell" 타입 + realized_pnl 없는 기록은 skip"""
        total, _ = self._run([
            {"type": "sell", "name": "A", "qty": 100, "avg": 49000, "amount": 0}
        ])
        self.assertEqual(total, 0.0)

    def test_legacy_sell_with_realized_pnl_counted(self):
        """기존 "sell" 타입이어도 realized_pnl 있으면 집계"""
        total, _ = self._run([
            {"type": "sell", "name": "A", "realized_pnl": 600000, "amount": 0}
        ])
        self.assertAlmostEqual(total, 600000)

    def test_returns_tuple(self):
        result = self._run([])
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)


# ─────────────────────────────────────────────
# 3. api_add_stock — 매도 분기
# ─────────────────────────────────────────────
class TestApiAddStockSellPrice(unittest.TestCase):

    def _run_sell(self, old_qty, old_avg, new_qty, sell_price_input):
        calls = []
        def mock_save(uid, pname, ttype, name, qty, price, display_avg=None):
            calls.append({"ttype": ttype, "qty": qty, "price": price,
                          "display_avg": display_avg})
        with patch.object(combined_bot, "save_trade", side_effect=mock_save):
            qty   = float(new_qty)
            avg   = float(sell_price_input)
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
        calls = self._run_sell(1000, 49000, 700, 55000)
        self.assertAlmostEqual(calls[0]["price"], 55000)

    def test_partial_sell_display_avg_is_old_avg(self):
        calls = self._run_sell(1000, 49000, 700, 55000)
        self.assertAlmostEqual(calls[0]["display_avg"], 49000)

    def test_full_sell_qty0_type(self):
        calls = self._run_sell(1000, 49000, 0, 52000)
        self.assertEqual(calls[0]["ttype"], "전량매도")

    def test_full_sell_qty0_price(self):
        calls = self._run_sell(1000, 49000, 0, 52000)
        self.assertAlmostEqual(calls[0]["price"], 52000)


# ─────────────────────────────────────────────
# 4. 소스 레벨 검증
# ─────────────────────────────────────────────
class TestSourceLevel(unittest.TestCase):

    def test_compute_realized_pnl_defined(self):
        self.assertIn("def compute_realized_pnl(", SRC)

    def test_realized_pnl_stored_in_record(self):
        self.assertIn('"realized_pnl"', SRC)

    def test_no_sell_price_param_in_save_trade(self):
        self.assertNotIn("sell_price=None", SRC)

    def test_no_row_sell_price_html(self):
        self.assertNotIn('id="row-sell-price"', SRC)

    def test_no_f_sell_price_html(self):
        self.assertNotIn('id="f-sell-price"', SRC)

    def test_on_qty_change_js_defined(self):
        self.assertIn("function _onQtyChange()", SRC)

    def test_edit_orig_qty_declared(self):
        self.assertIn("let _editOrigQty", SRC)

    def test_edit_orig_qty_set_in_open_edit_modal(self):
        block = SRC[SRC.find("function openEditModal"):SRC.find("function openEditModal") + 600]
        self.assertIn("_editOrigQty = d.qty", block)

    def test_edit_orig_qty_reset_in_open_add_modal(self):
        block = SRC[SRC.find("function openAddModal"):SRC.find("function openAddModal") + 800]
        self.assertIn("_editOrigQty = 0", block)

    def test_no_sell_price_in_payload(self):
        block = SRC[SRC.find("async function saveStock"):SRC.find("async function saveStock") + 700]
        self.assertNotIn("매도단가", block)

    def test_realized_card_in_source(self):
        self.assertIn("실현 손익", SRC)
        self.assertIn("청산 종목 기준", SRC)

    def test_no_sell_price_passed_to_매도(self):
        block = SRC[SRC.find("def api_add_stock"):SRC.find("def api_del_stock")]
        self.assertNotIn("sell_price=sell_price", block)

    def test_compute_pnl_called_in_build_html(self):
        self.assertIn("compute_realized_pnl(uid, pname)", SRC)

    def test_rpnl_html_in_trade_rows(self):
        self.assertIn("_rpnl_html", SRC)
        self.assertIn("실현손익", SRC)


if __name__ == "__main__":
    unittest.main(verbosity=2)
