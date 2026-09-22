import math
import pandas as pd


def calculate_metrics(equity: pd.Series, trades: list[dict], buy_hold: float | None, config, start: str, end: str) -> dict:
    values = pd.to_numeric(equity, errors="coerce").dropna()
    if values.empty:
        raise ValueError("回测没有生成资金曲线")
    daily = values.pct_change().replace([float("inf"), float("-inf")], pd.NA).dropna()
    total = float(values.iloc[-1] / values.iloc[0] - 1)
    days = max((pd.Timestamp(end) - pd.Timestamp(start)).days, 1)
    annual = float((1 + total) ** (365.25 / days) - 1) if 1 + total > 0 else -1.0
    peak = values.cummax()
    drawdown = values / peak - 1
    max_dd = float(drawdown.min())
    trough_date = drawdown.idxmin()
    peak_date = values.loc[:trough_date].idxmax()
    recovery = values.loc[trough_date:][values.loc[trough_date:] >= values.loc[:trough_date].max()]
    duration = int((recovery.index[0] - peak_date).days) if not recovery.empty else int((values.index[-1] - peak_date).days)
    sharpe = float(daily.mean() / daily.std(ddof=1) * math.sqrt(252)) if len(daily) > 1 and daily.std(ddof=1) else None
    completed = [t for t in trades if t.get("exit_date") is not None and t.get("status") != "open_at_end"]
    returns = pd.Series([float(t.get("net_return_pct", t.get("return_pct", 0)) or 0) for t in completed], dtype=float)
    wins, losses = returns[returns > 0], returns[returns <= 0]
    avg_loss = float(losses.mean()) if not losses.empty else None
    avg_profit = float(wins.mean()) if not wins.empty else None
    result = {
        "total_return": total, "annualized_return": annual, "max_drawdown": max_dd,
        "max_drawdown_duration_days": duration, "calmar_ratio": annual / abs(max_dd) if max_dd else None,
        "sharpe_ratio": sharpe, "trade_count": len(completed),
        "winning_trades": len(wins), "losing_trades": len(losses),
        "win_rate": len(wins) / len(completed) if completed else None,
        "average_trade_return": float(returns.mean()) if not returns.empty else None,
        "average_profit": avg_profit, "average_loss": avg_loss,
        "profit_loss_ratio": avg_profit / abs(avg_loss) if avg_profit is not None and avg_loss else None,
        "average_holding_days": float(pd.Series([t.get("holding_days", 0) for t in completed]).mean()) if completed else None,
        "max_trade_profit": float(returns.max()) if not returns.empty else None,
        "max_trade_loss": float(returns.min()) if not returns.empty else None,
        "first_sell_count": sum(t.get("exit_reason") == "first_sell" for t in completed),
        "second_sell_count": sum(t.get("exit_reason") == "second_sell" for t in completed),
        "third_sell_count": sum(t.get("exit_reason") == "third_sell" for t in completed),
        "atr_stop_count": sum(t.get("exit_reason") == "atr_stop" for t in completed),
        "breakeven_stop_count": sum(t.get("exit_reason") == "breakeven_stop" for t in completed),
        "profit_lock_stop_count": sum(t.get("exit_reason") == "profit_lock_stop" for t in completed),
        "initial_zg_stop_count": sum(t.get("exit_reason") == "initial_zg_stop" for t in completed),
        "fallback_stop_count": sum(t.get("exit_reason") == "fallback_stop" for t in completed),
        "final_close_count": sum(t.get("exit_reason") == "final_close" for t in completed),
        "manual_or_other_count": sum(t.get("exit_reason") == "manual_or_other" for t in completed),
        "open_trade_count": sum(t.get("status") == "open_at_end" for t in trades),
        "total_fees": float(sum(float(t.get("fee", 0) or 0) for t in completed)),
        "exit_reason_share": {reason: sum(t.get("exit_reason") == reason for t in completed) / len(completed) if completed else 0.0 for reason in ("first_sell", "second_sell", "third_sell", "atr_stop", "breakeven_stop", "profit_lock_stop", "initial_zg_stop", "fallback_stop", "final_close", "manual_or_other")},
        "buy_hold_diff": total - buy_hold if buy_hold is not None else None,
        "low_confidence": len(completed) < config.min_trades,
        "confidence": "very_low" if len(completed) < 3 else "low" if len(completed) < 10 else "medium" if len(completed) < 30 else "higher",
    }
    return result, drawdown
