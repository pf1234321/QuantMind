"""内部缠论买卖信号识别与信号状态模型。"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import pandas as pd

from .chan import build_centers, build_strokes, detect_fractals

SIGNAL_TYPES = {"first_buy", "second_buy", "third_buy", "first_sell", "second_sell", "third_sell"}
SIGNAL_STATUSES = {"detected", "confirmed", "invalidated", "expired", "planned", "accepted", "executed", "rejected", "cancelled"}

@dataclass
class ChanSignal:
    stock_code: str
    signal_type: str
    signal_date: str
    confirmed_date: str | None = None
    execution_date: str | None = None
    signal_status: str = "confirmed"
    signal_level: str = "daily"
    signal_price: float | None = None
    center_lower: float | None = None
    center_upper: float | None = None
    signal_strength: str = "medium"
    confidence: str = "medium"
    atr_value: float | None = None
    atr_exit_mult: float | None = None
    lookahead_risk: bool = False
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_chan_signals(frame: pd.DataFrame, stock_code: str = "", end_date=None) -> list[dict[str, Any]]:
    """在截止日之前识别结构信号；结构确认后才输出，禁止使用截止日之后数据。"""
    if frame.empty or not {"open", "high", "low", "close"}.issubset(frame.columns):
        return []
    data = frame.sort_index().copy()
    if end_date is not None:
        data = data.loc[data.index <= pd.Timestamp(end_date)]
    if len(data) < 8:
        return []
    fractals = detect_fractals(data)
    # 右侧确认：t 分型在 t+1 收盘后才可用于扫描。
    strokes = build_strokes(data, fractals)
    centers = build_centers(strokes)
    atr_series = _atr(data)
    rows: list[dict[str, Any]] = []
    last_first_buy_index: int | None = None
    last_first_buy_pivot_low: float | None = None
    first_buy_cooldown = 20
    for i in range(2, len(data)):
        date = data.index[i]
        row = data.iloc[i]
        pivot = data.iloc[i - 1]
        is_bottom_confirmed = bool(fractals.iloc[i - 1].bottom_fractal)
        prior_lows = data.iloc[max(0, i - 11):i - 1].low
        strict_first_buy = (
            is_bottom_confirmed
            and len(prior_lows) >= 8
            and float(pivot.low) < float(prior_lows.min())
            and float(row.close) > float(row.open)
            and float(row.close) > float(pivot.high)
            and (last_first_buy_index is None or i - last_first_buy_index >= first_buy_cooldown)
            and (last_first_buy_pivot_low is None or float(row.close) < last_first_buy_pivot_low or float(pivot.low) < last_first_buy_pivot_low)
        )
        if strict_first_buy:
            last_first_buy_index = i
            last_first_buy_pivot_low = float(pivot.low)
        if is_bottom_confirmed and row.close > row.open:
            signal_type = "first_buy" if strict_first_buy else ("third_buy" if len(centers) and float(row.close) > float(centers.iloc[-1].upper) else "second_buy")
            rows.append(_make(stock_code, signal_type, date, row, atr_series.iloc[i], centers, pivot_date=data.index[i - 1]))
        if bool(fractals.iloc[i - 1].top_fractal) and row.close < row.open:
            prior_highs = data.iloc[max(0, i - 5):i - 1].high
            is_first_sell = len(prior_highs) >= 3 and float(data.iloc[i - 1].high) >= float(prior_highs.max())
            signal_type = "first_sell" if is_first_sell else ("third_sell" if len(centers) and float(row.close) < float(centers.iloc[-1].lower) else "second_sell")
            rows.append(_make(stock_code, signal_type, date, row, atr_series.iloc[i], centers, pivot_date=data.index[i - 1]))
    return rows


def _make(code, signal_type, date, row, atr, centers, pivot_date=None):
    center = centers.iloc[-1] if len(centers) else None
    return {
        **ChanSignal(code, signal_type, str(pd.Timestamp(date).date()), str(pd.Timestamp(date).date()), signal_price=float(row.close), center_lower=float(center.lower) if center is not None else None, center_upper=float(center.upper) if center is not None else None, signal_strength="high" if signal_type in {"third_buy", "third_sell"} else "medium", confidence="medium", atr_value=float(atr) if pd.notna(atr) else None).to_dict(),
        "pivot_date": str(pd.Timestamp(pivot_date or date).date()),
    }


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous = frame.close.shift(1)
    return pd.concat([frame.high - frame.low, (frame.high - previous).abs(), (frame.low - previous).abs()], axis=1).max(axis=1).rolling(period, min_periods=period).mean()
