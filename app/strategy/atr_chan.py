"""QuantMind 内部缠论 ATR 策略。"""
from __future__ import annotations

import pandas as pd

from app.backtest.config import BacktestConfig
from app.backtest.contracts import BacktestResult, StrategyAdapter
from app.strategy.chan_signal import build_signal_frame


def run_atr_chan(frame: pd.DataFrame, atr_exit_mult: float, config: BacktestConfig) -> BacktestResult:
    if frame.empty:
        return BacktestResult(pd.Series(dtype=float), [], {"strategy": "internal_chan_atr"})
    data = build_signal_frame(frame.sort_index())
    cash = float(config.initial_cash)
    shares = 0.0
    entry_price = None
    entry_date = None
    highest = None
    trades = []
    equity = []
    for i, (date, row) in enumerate(data.iterrows()):
        close = float(row.close)
        if shares == 0 and bool(row.buy_signal) and i + 1 < len(data):
            next_open = float(data.iloc[i + 1].open) * (1 + config.slippage)
            shares = cash * config.position_pct / next_open
            fee = shares * next_open * config.commission
            cash -= shares * next_open + fee
            entry_price, entry_date, highest = next_open, data.index[i + 1], next_open
        elif shares > 0:
            highest = max(highest, close)
            stop = highest - float(row.atr) * float(atr_exit_mult) if pd.notna(row.atr) else None
            reason = "atr_stop" if stop is not None and close <= stop else "third_sell" if bool(row.sell_signal) else None
            if reason and i + 1 < len(data):
                exit_price = float(data.iloc[i + 1].open) * (1 - config.slippage)
                fee = shares * exit_price * config.commission
                cash += shares * exit_price - fee
                gross = (exit_price - entry_price) * shares
                trades.append({"entry_date": entry_date, "entry_price": entry_price, "entry_quantity": shares, "exit_date": data.index[i + 1], "exit_price": exit_price, "exit_quantity": shares, "gross_profit": gross, "fee": fee, "net_profit": gross - fee, "return_pct": exit_price / entry_price - 1, "net_return_pct": (gross - fee) / (entry_price * shares), "holding_days": (data.index[i + 1] - entry_date).days, "exit_reason": reason, "execution_status": "filled"})
                shares = 0.0
                entry_price = entry_date = highest = None
        equity.append(cash + shares * close)
    if shares > 0:
        trades.append({"entry_date": entry_date, "entry_price": entry_price, "entry_quantity": shares, "exit_date": None, "exit_price": None, "exit_quantity": 0, "gross_profit": None, "fee": None, "net_profit": None, "return_pct": None, "net_return_pct": None, "holding_days": None, "exit_reason": None, "execution_status": "open"})
    return BacktestResult(pd.Series(equity, index=data.index, dtype=float), trades, {"strategy": "internal_chan_atr", "signal_mode": "strict_no_lookahead", "lookahead_risk": False})


def build_internal_adapter() -> StrategyAdapter:
    return StrategyAdapter(run=run_atr_chan, source_description="QuantMind internal chan ATR", run_mode="strict_no_lookahead", lookahead_risk=False)
