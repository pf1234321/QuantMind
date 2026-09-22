import unittest
from unittest.mock import patch

import pandas as pd

from app.services.qlib_data_adapter import QlibDataAdapter


class QlibDataAdapterTest(unittest.TestCase):
    def setUp(self):
        self.adapter = QlibDataAdapter()

    def test_normalize_code(self):
        self.assertEqual(self.adapter.normalize_code("000001"), "SZ000001")
        self.assertEqual(self.adapter.normalize_code("600000.SH"), "SH600000")
        self.assertEqual(self.adapter.normalize_code("430001"), "BJ430001")

    def test_validate_dates(self):
        self.assertEqual(
            self.adapter.validate_dates("2022-01-04", "2026-08-24"),
            ("2022-01-04", "2026-08-24"),
        )
        with self.assertRaises(ValueError):
            self.adapter.validate_dates("2026-08-25", "2026-08-24")
        with self.assertRaises(ValueError):
            self.adapter.validate_dates("20220104", "2026-08-24")

    @patch("app.services.qlib_data_adapter.execute_query")
    def test_get_data_maps_qlib_fields_without_writing(self, execute_query):
        execute_query.return_value = [
            {
                "stock_code": "000001",
                "trade_date": "2022-01-04",
                "open_price": 10,
                "high_price": 11,
                "low_price": 9,
                "close_price": 10.5,
                "volume": 1000,
                "amount": 20000,
                "adjustflag": 2,
            }
        ]
        frame = self.adapter.get_data(["000001"], "2022-01-04", "2022-01-04")
        self.assertEqual(list(frame["instrument"]), ["SZ000001"])
        self.assertEqual(list(frame["close"]), [10.5])
        self.assertEqual(list(frame["datetime"]), [pd.Timestamp("2022-01-04")])
        self.assertIn("adjustflag", frame.columns)
        execute_query.assert_called_once()
        self.assertNotIn("INSERT", execute_query.call_args.args[0].upper())

    @patch("app.services.qlib_data_adapter.execute_query")
    def test_validate_data_blocks_invalid_ohlc(self, execute_query):
        execute_query.side_effect = [
            [{
                "min_trade_date": "2022-01-04",
                "max_trade_date": "2022-01-04",
                "stock_count": 1,
                "trade_date_count": 1,
                "row_count": 1,
            }],
            [{"stock_code": "000001"}],
            [{
                "stock_code": "000001",
                "trade_date": "2022-01-04",
                "open_price": 10,
                "high_price": 9,
                "low_price": 8,
                "close_price": 8.5,
                "volume": 1000,
                "amount": 20000,
                "adjustflag": 2,
            }],
        ]
        report = self.adapter.validate_data(["000001"], "2022-01-04", "2022-01-04")
        self.assertEqual(report.status, "blocked")
        self.assertTrue(any(issue["issue_type"] == "invalid_ohlc" for issue in report.issues))

    @patch("app.services.qlib_data_adapter.execute_query")
    def test_coverage_empty_data_is_blocked(self, execute_query):
        execute_query.return_value = [{
            "min_trade_date": None,
            "max_trade_date": None,
            "stock_count": 0,
            "trade_date_count": 0,
            "row_count": 0,
        }]
        report = self.adapter.get_coverage(["000001"], "2022-01-04", "2022-01-05")
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.row_count, 0)
        self.assertEqual(report.issues[0]["issue_type"], "no_data")

    @patch("app.services.qlib_data_adapter.execute_query")
    def test_status_includes_sync_time_and_pipeline(self, execute_query):
        execute_query.side_effect = [
            [{"min_trade_date": "2022-01-04", "max_trade_date": "2026-08-24", "stock_count": 2, "trade_date_count": 100, "row_count": 200}],
            [{"finished_at": "2026-08-25 06:30:00"}],
        ]
        status = self.adapter.get_status()
        self.assertEqual(status["status"], "healthy")
        self.assertEqual(status["pipeline"], "trade_stock_daily → Qlib Adapter → Alpha158")
        self.assertEqual(status["last_sync_at"], "2026-08-25 06:30:00")
        self.assertEqual(status["last_sync_source"], "sync_log")

    @patch("app.services.qlib_data_adapter.execute_query")
    def test_status_returns_unavailable_without_fake_statistics(self, execute_query):
        execute_query.side_effect = RuntimeError("database down")
        status = self.adapter.get_status()
        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(status["connection_status"], "disconnected")
        self.assertIsNone(status["min_trade_date"])
        self.assertEqual(status["row_count"], 0)


if __name__ == "__main__":
    unittest.main()
