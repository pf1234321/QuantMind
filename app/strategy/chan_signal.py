"""严格无前视的缠论风格买卖信号。"""
from __future__ import annotations

import pandas as pd
from .chan import build_strokes, detect_fractals


def build_signal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """使用确认后的分型，在下一根 K 线执行，避免使用未来收盘价。"""
    result = frame.copy()
    fractals = detect_fractals(result)
    # 分型在 t+1 才确认，因此将 t 的结构信号右移一日。
    result["bottom_confirmed"] = fractals["bottom_fractal"].shift(1, fill_value=False)
    result["top_confirmed"] = fractals["top_fractal"].shift(1, fill_value=False)
    result["atr"] = _atr(result, 14)
    result["buy_signal"] = result["bottom_confirmed"] & (result["close"] > result["open"])
    result["sell_signal"] = result["top_confirmed"] & (result["close"] < result["open"])
    result["strokes"] = len(build_strokes(result, fractals))
    return result


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    previous = frame.close.shift(1)
    true_range = pd.concat([frame.high - frame.low, (frame.high - previous).abs(), (frame.low - previous).abs()], axis=1).max(axis=1)
    return true_range.rolling(period, min_periods=period).mean()
