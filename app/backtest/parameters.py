"""ATR 参数生命周期：指标每日更新，倍数月检季度验。"""
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class ParameterState:
    atr_period: int = 14
    atr_exit_mult: float = 2.5
    parameter_version: str = "initial"
    effective_date: str | None = None

def daily_atr_update(frame, period: int = 14):
    if period <= 0: raise ValueError("ATR period 必须为正数")
    tr = __import__("pandas").concat([frame.high-frame.low, (frame.high-frame.close.shift()).abs(), (frame.low-frame.close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()

def monthly_health_check(summary: dict, min_trades: int = 3) -> dict:
    trades = int(summary.get("trade_count", 0) or 0)
    drawdown = summary.get("max_drawdown")
    healthy = trades >= min_trades and (drawdown is None or float(drawdown) >= -1.0)
    return {"parameter_health": "healthy" if healthy else "review_required", "warning": None if healthy else "近期样本或风险指标不足，建议季度重新验证", "trade_count": trades}

def quarterly_parameter_decision(candidates: list[dict], current: ParameterState, max_drawdown: float | None = None) -> dict:
    eligible = [row for row in candidates if int(row.get("trade_count", 0) or 0) >= 10 and (max_drawdown is None or float(row.get("max_drawdown", -1)) >= -abs(max_drawdown)) and not row.get("concentration_risk", False)]
    if not eligible: return {"changed": False, "state": current, "reason": "没有通过季度样本、回撤和集中度门槛的参数"}
    chosen = max(eligible, key=lambda row: (float(row.get("calmar_ratio") or -999), float(row.get("sharpe_ratio") or -999)))
    multiplier = float(chosen["atr_exit_mult"])
    if multiplier == current.atr_exit_mult: return {"changed": False, "state": current, "reason": "当前参数仍满足季度验证条件"}
    effective = str(date.today())
    state = ParameterState(current.atr_period, multiplier, f"quarterly-{effective}", effective)
    return {"changed": True, "state": state, "old_multiplier": current.atr_exit_mult, "new_multiplier": multiplier, "effective_date": effective, "reason": "季度滚动验证通过"}
