import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.signals import SignalStore
from app.strategy.signals import detect_chan_signals


class SignalStoreTest(unittest.TestCase):
    def test_upsert_deduplicates_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SignalStore(Path(directory) / "signals.jsonl")
            signal = {"stock_code": "000001", "signal_type": "third_buy", "signal_date": "2026-01-02", "signal_level": "daily"}
            store.upsert(signal)
            store.upsert({**signal, "confidence": "high"})
            rows = store.list(stock_code="000001")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["confidence"], "high")

    def test_signal_types_are_explicit(self):
        dates = pd.date_range("2025-01-01", periods=30, freq="D")
        close = pd.Series([10, 9, 11, 8, 12, 9, 13, 10, 14, 11] * 3, index=dates)
        frame = pd.DataFrame({"open": close - 0.2, "high": close + 0.5, "low": close - 0.5, "close": close})
        rows = detect_chan_signals(frame, "000001", dates[-1])
        self.assertTrue(all(row["signal_type"] in {"first_buy", "second_buy", "third_buy", "first_sell", "second_sell", "third_sell"} for row in rows))

    def test_strict_first_buy_has_cooldown_and_pivot_date(self):
        dates = pd.date_range("2025-01-01", periods=70, freq="D")
        close = pd.Series([20, 19, 18, 17, 16, 17, 18, 16, 15, 14, 15, 16, 14, 13, 14, 15, 13, 12, 13, 14, 12, 11, 12, 13, 11, 10, 11, 12, 10, 9, 10, 11, 9, 8, 9, 10, 8, 7, 8, 9, 7, 6, 7, 8, 6, 5, 6, 7, 5, 4, 5, 6, 4, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19], index=dates)
        frame = pd.DataFrame({"open": close - 0.3, "high": close + 0.5, "low": close - 0.5, "close": close})
        rows = detect_chan_signals(frame, "000001", dates[-1])
        first_buys = [row for row in rows if row["signal_type"] == "first_buy"]
        self.assertTrue(first_buys)
        self.assertTrue(all("pivot_date" in row for row in first_buys))
        self.assertTrue(all((pd.Timestamp(first_buys[i + 1]["signal_date"]) - pd.Timestamp(first_buys[i]["signal_date"])).days >= 20 for i in range(len(first_buys) - 1)))


if __name__ == "__main__":
    unittest.main()
