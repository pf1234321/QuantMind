import unittest

import pandas as pd

from app.backtest.config import BacktestConfig
from app.backtest.contracts import BacktestResult, StrategyAdapter
from app.backtest.data import normalize_daily_bars
from app.backtest.runner import scan_atr_exit_mult
from app.backtest.validation import validate_multipliers


class AtrBacktestTest(unittest.TestCase):
    def test_validate_default_and_range(self):
        self.assertEqual(validate_multipliers()[4], 2.5)
        self.assertEqual(validate_multipliers(range_start=1.5, range_end=2.0, step=0.25), (1.5, 1.75, 2.0))

    def test_validate_rejects_invalid_range(self):
        with self.assertRaises(ValueError):
            validate_multipliers(range_start=2, range_end=1, step=0.5)

    def test_normalize_bars_sorts_and_maps(self):
        frame = normalize_daily_bars([
            {"trade_date": "2024-01-02", "open_price": 2, "high_price": 3, "low_price": 1, "close_price": 2.5},
            {"trade_date": "2024-01-01", "open_price": 1, "high_price": 2, "low_price": 0.5, "close_price": 1.5},
        ])
        self.assertEqual(list(frame.index.strftime("%Y-%m-%d")), ["2024-01-01", "2024-01-02"])
        self.assertEqual(frame.close.iloc[0], 1.5)

    def test_scan_reuses_same_data_and_marks_baseline(self):
        index = pd.date_range("2024-01-01", periods=5, freq="D")
        data = pd.DataFrame({"open": [1] * 5, "high": [2] * 5, "low": [1] * 5, "close": [1, 1.1, 1.2, 1.0, 1.1]}, index=index)

        def run(frame, multiplier, config):
            trades = [{"entry_date": index[0], "entry_price": 1, "exit_date": index[-1], "exit_price": 1.1, "return_pct": 0.1, "holding_days": 4, "exit_reason": "atr_stop"}]
            return BacktestResult(frame.close * (1 + multiplier / 100), trades)

        result = scan_atr_exit_mult(
            start_date="2024-01-01", end_date="2024-01-05", multipliers=[2.5, 3.0],
            adapter=StrategyAdapter(run, "test", lookahead_risk=True), data=data,
            config=BacktestConfig(min_trades=1), evaluate_periods=False,
        )
        self.assertEqual(set(result.summary.atr_exit_mult), {2.5, 3.0})
        self.assertTrue(bool(result.summary.loc[result.summary.atr_exit_mult == 2.5, "is_baseline"].iloc[0]))
        self.assertTrue(result.report["lookahead_risk"])
        self.assertEqual(len(result.trades), 2)


if __name__ == "__main__":
    unittest.main()
