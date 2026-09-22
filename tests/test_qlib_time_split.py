import unittest
from unittest.mock import patch

from app.services.qlib_data_adapter import CoverageReport
from app.services.qlib_time_split import FixedTimeSplitService


class FixedTimeSplitServiceTest(unittest.TestCase):
    def test_fixed_configuration_is_ordered_and_non_overlapping(self):
        FixedTimeSplitService.validate_configuration()
        self.assertEqual(FixedTimeSplitService.RESEARCH.start, "2022-01-04")
        self.assertEqual(FixedTimeSplitService.STAGES["train"].end, "2024-12-31")
        self.assertEqual(FixedTimeSplitService.STAGES["validation"].start, "2025-01-01")
        self.assertEqual(FixedTimeSplitService.STAGES["test"].start, "2026-01-01")

    def test_custom_dates_are_rejected(self):
        with self.assertRaises(ValueError):
            FixedTimeSplitService.assert_fixed_dates("2022-01-01", "2026-08-24")
        with self.assertRaises(ValueError):
            FixedTimeSplitService.assert_fixed_dates("2022-01-04", "2026-08-25")

    @patch("app.services.qlib_time_split.adapter")
    def test_snapshot_collects_each_stage_and_blocks_missing_data(self, data_adapter):
        data_adapter.normalize_stock_codes.return_value = ["000001"]
        data_adapter.get_coverage.side_effect = [
            CoverageReport("trade_stock_daily", "qlib", "healthy", "2022-01-04", "2024-12-31", 1, 1, 700, 2),
            CoverageReport("trade_stock_daily", "qlib", "blocked", None, None, 0, 0, 0, 2, issues=[{"message": "无数据", "blocked": True}]),
            CoverageReport("trade_stock_daily", "qlib", "healthy", "2026-01-01", "2026-08-24", 1, 1, 150, 2),
        ]
        service = FixedTimeSplitService(data_adapter)
        snapshot = service.build_snapshot(["000001"])
        self.assertEqual(snapshot.status, "blocked")
        self.assertEqual(list(snapshot.stages), ["train", "validation", "test"])
        self.assertEqual(snapshot.stages["train"].row_count, 700)
        self.assertTrue(snapshot.errors)


if __name__ == "__main__":
    unittest.main()
