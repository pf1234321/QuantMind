import unittest
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd

from app.api.sector_opportunities import list_opportunities
from app.services.sector_opportunity import _phase, _sector_metrics, _stock_candidates, _zscore


class SectorOpportunityTest(unittest.TestCase):
    @patch("app.api.sector_opportunities.list_sector_opportunities", return_value={"items": []})
    def test_empty_phase_is_treated_as_unfiltered(self, list_opportunities_mock):
        result = list_opportunities(2, "", "", None, None, None, None, None, 1, 20)
        self.assertEqual(result, {"items": []})
        self.assertIsNone(list_opportunities_mock.call_args.args[2])

    def test_zscore_is_cross_sectional_and_zero_mean(self):
        values = _zscore(pd.Series([1.0, 2.0, 3.0]))
        self.assertAlmostEqual(float(values.mean()), 0.0, places=8)
        self.assertGreater(values.iloc[-1], values.iloc[0])

    def test_phase_returns_neutral_when_history_is_insufficient(self):
        self.assertEqual(_phase(pd.Series(np.linspace(1, 2, 20))), "neutral")

    def test_sector_metrics_requires_latest_trade_date(self):
        latest = date(2026, 8, 21)
        dates = [latest - timedelta(days=offset) for offset in range(79, -1, -1)]
        frame = pd.DataFrame([
            {
                "sector_name": "测试行业",
                "sector_level": 2,
                "trade_date": trade_date,
                "close_idx": 1000 + index,
                "total_amount": 1000000,
                "rise_count": 3,
                "fall_count": 2,
                "kline_stock_count": 8,
                "stock_count": 10,
                "top_stock": "000001",
                "top_stock_name": "测试股",
            }
            for index, trade_date in enumerate(dates)
        ])
        metrics = _sector_metrics(frame, latest)
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics.iloc[0]["trade_date"], latest)
        self.assertIn("strength_score", metrics.columns)
        self.assertIn("rs_60", metrics.columns)

    @patch("app.services.sector_opportunity.get_sector_member_codes", return_value=["000001"])
    @patch("app.services.sector_opportunity.execute_query")
    def test_stock_candidates_reject_invalid_ohlc(self, execute_query, _members):
        latest = date(2026, 8, 21)
        rows = []
        for index in range(61):
            trade_date = latest - timedelta(days=60 - index)
            rows.append({
                "stock_code": "000001",
                "stock_name": "测试股",
                "trade_date": trade_date,
                "open_price": 10,
                "high_price": 9,
                "low_price": 8,
                "close_price": 8.5,
                "volume": 1000,
                "amount": 100000,
                "turnover_rate": 1,
            })
        execute_query.return_value = rows
        self.assertEqual(_stock_candidates("测试行业", 2, latest, 5), [])

    @patch("app.services.sector_opportunity.get_sector_member_codes", return_value=["000001"])
    @patch("app.services.sector_opportunity.execute_query")
    def test_stock_candidates_calculate_weighted_score(self, execute_query, _members):
        latest = date(2026, 8, 21)
        rows = []
        for index in range(61):
            close = 10 + index * 0.1
            trade_date = latest - timedelta(days=60 - index)
            rows.append({
                "stock_code": "000001",
                "stock_name": "测试股",
                "trade_date": trade_date,
                "open_price": close - 0.05,
                "high_price": close + 0.1,
                "low_price": close - 0.1,
                "close_price": close,
                "volume": 1000,
                "amount": 100000,
                "turnover_rate": 1,
            })
        execute_query.return_value = rows
        candidates = _stock_candidates("测试行业", 2, latest, 5)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        expected = candidate["roc_20"] * 0.4 + candidate["roc_60"] * 0.3 + candidate["roc_5"] * 0.3
        self.assertAlmostEqual(candidate["stock_score"], expected, places=8)
        self.assertEqual(candidate["stock_rank"], 1)


if __name__ == "__main__":
    unittest.main()
