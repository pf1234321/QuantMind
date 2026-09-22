import unittest

import pandas as pd

from app.backtest.config import BacktestConfig
from app.strategy.atr_chan import build_internal_adapter, run_atr_chan
from app.strategy.chan import detect_fractals


class InternalChanTest(unittest.TestCase):
    def test_fractals_are_detected(self):
        frame = pd.DataFrame({"high": [2, 3, 2], "low": [1, 2, 1], "open": [1, 2, 1], "close": [2, 2, 2]})
        result = detect_fractals(frame)
        self.assertTrue(bool(result.iloc[1].top_fractal))

    def test_internal_adapter_is_no_lookahead(self):
        adapter = build_internal_adapter()
        self.assertEqual(adapter.run_mode, "strict_no_lookahead")
        self.assertFalse(adapter.lookahead_risk)

    def test_empty_frame_returns_result(self):
        result = run_atr_chan(pd.DataFrame(), 2.5, BacktestConfig())
        self.assertTrue(result.equity.empty)
        self.assertEqual(result.metadata["strategy"], "internal_chan_atr")


if __name__ == "__main__":
    unittest.main()
