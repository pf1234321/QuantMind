import unittest

import pandas as pd

from app.backtest.daily import run_daily_scan
from app.backtest.parameters import ParameterState, daily_atr_update, monthly_health_check
from app.backtest.trade_tracking import pair_completed_orders
from app.backtest.universe import UniverseConfig, filter_stock


class TradeTrackingTest(unittest.TestCase):
    def test_completed_orders_pair_fifo_and_ignore_rejected(self):
        trades, open_trades = pair_completed_orders([
            {"side": "BUY", "status": "completed", "date": "2024-01-01", "price": 10, "quantity": 100},
            {"side": "BUY", "status": "completed", "date": "2024-01-02", "price": 11, "quantity": 50},
            {"side": "SELL", "status": "rejected", "date": "2024-01-03", "price": 12, "quantity": 150},
            {"side": "SELL", "status": "completed", "date": "2024-01-04", "price": 12, "quantity": 120},
        ], "300750", 2.5)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["entry_quantity"], 100)
        self.assertEqual(trades[1]["entry_quantity"], 20)
        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0]["status"], "open_at_end")

    def test_exit_reason_is_attached_to_completed_fill(self):
        from app.backtest.trade_tracking import OrderTradeTracker
        tracker = OrderTradeTracker("300750", 2.5)
        tracker.notify_order({"side": "BUY", "status": "filled", "date": "2024-01-01", "price": 10, "quantity": 100})
        tracker.set_exit_reason("atr_stop", ["atr_stop", "third_sell"])
        tracker.notify_order({"side": "SELL", "status": "filled", "date": "2024-01-02", "price": 9, "quantity": 100})
        self.assertEqual(tracker.trades[0]["exit_reason"], "atr_stop")
        self.assertEqual(tracker.trades[0]["exit_triggered_rules"], "atr_stop,third_sell")


class UniverseAndDailyTest(unittest.TestCase):
    def test_universe_filters_short_history_and_low_price(self):
        index = pd.date_range("2024-01-01", periods=3)
        frame = pd.DataFrame({"open": [1, 1, 1], "high": [2, 2, 2], "low": [0.8, 0.8, 0.8], "close": [1, 1, 1], "amount": [100, 100, 100]}, index=index)
        result = filter_stock("000001", frame, config=UniverseConfig(min_listing_days=5, min_price=3))
        self.assertFalse(result["eligible"])
        self.assertIn("insufficient_history", result["filter_reason"])

    def test_daily_scan_is_strict_no_lookahead(self):
        index = pd.date_range("2024-01-01", periods=3)
        frame = pd.DataFrame({"open": [1, 1, 1], "high": [2, 2, 2], "low": [0.8, 0.8, 0.8], "close": [1, 1.1, 1.2]}, index=index)
        calls = []
        def provider(data, end_date, mode):
            calls.append((data.index.max(), end_date, mode))
            return {"candidates": [{"signal_type": "buy"}]}
        report = run_daily_scan({"000001": frame}, provider, end_date="2024-01-02")
        self.assertEqual(calls[0][0], pd.Timestamp("2024-01-02"))
        self.assertEqual(calls[0][2], "strict_no_lookahead")
        self.assertFalse(report.report["lookahead_risk"])

    def test_atr_lifecycle(self):
        frame = pd.DataFrame({"high": [2, 3, 4], "low": [1, 2, 3], "close": [1.5, 2.5, 3.5]})
        self.assertTrue(pd.isna(daily_atr_update(frame, 14).iloc[-1]))
        self.assertEqual(monthly_health_check({"trade_count": 0})["parameter_health"], "review_required")
        self.assertEqual(ParameterState().atr_exit_mult, 2.5)


if __name__ == "__main__":
    unittest.main()
