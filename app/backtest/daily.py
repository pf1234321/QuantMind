"""每日收盘后研究、模拟和实盘辅助扫描。"""
from dataclasses import dataclass
from pathlib import Path
import json
import pandas as pd

from app.strategy.chanpy_adapter import chanpy_available, detect_chanpy_signals
from app.signals import SignalStore

@dataclass
class DailyScanReport:
    candidates: pd.DataFrame
    exits: pd.DataFrame
    plan: pd.DataFrame
    report: dict

def _latest_completed_date(frames, end_date=None):
    if end_date is not None:
        return pd.Timestamp(end_date)
    dates = [pd.Timestamp(index.max()) for frame in frames.values() if not frame.empty for index in [frame.index]]
    if not dates:
        raise ValueError("股票数据为空")
    return min(dates).normalize()

def _atr(frame, period=14):
    tr = pd.concat([frame.high - frame.low, (frame.high - frame.close.shift()).abs(), (frame.low - frame.close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()

def _scan_frames(frames, signal_provider, end_date, atr_exit_mult, signal_mode, portfolio=None):
    candidates, exits, pending = [], [], []
    portfolio = portfolio or {}
    holdings = portfolio.get("holdings", {}) if isinstance(portfolio, dict) else {}
    signal_store = portfolio.get("signal_store") if isinstance(portfolio, dict) else None
    signal_store = signal_store or SignalStore()
    for code, frame in sorted(frames.items()):
        cut = frame.loc[frame.index <= end_date].copy()
        if cut.empty:
            continue
        if not {"high", "low", "close"}.issubset(cut.columns):
            continue
        atr_value = _atr(cut).iloc[-1]
        result = signal_provider(cut, end_date, mode=signal_mode) if signal_provider else {"candidates": detect_chanpy_signals(cut, code, end_date)}
        result = result if isinstance(result, dict) else {}
        detected = result.get("candidates", [])
        if not detected and signal_provider is not None:
            detected = detect_chanpy_signals(cut, code, end_date)
        pending_signals = [
            {
                **item,
                "stock_code": code,
                "signal_date": item.get("signal_date", str(end_date.date())),
                "atr_exit_mult": atr_exit_mult,
                "atr_value": item.get("atr_value", float(atr_value) if pd.notna(atr_value) else None),
                "lookahead_risk": signal_mode == "full_history",
            }
            for item in detected
        ]
        pending.extend(pending_signals)
        holding = holdings.get(code)
        if holding:
            high_water = max(float(holding.get("highest_price", holding.get("entry_price", 0))), float(cut.close.max()))
            stop = high_water - float(atr_value) * atr_exit_mult if pd.notna(atr_value) else None
            if stop is not None and float(cut.close.iloc[-1]) <= stop:
                exits.append({"stock_code": code, "signal_date": str(end_date.date()), "current_price": float(cut.close.iloc[-1]), "atr_value": float(atr_value), "stop_price": stop, "exit_reason": "atr_stop", "urgency": "high"})
    candidates = signal_store.upsert_many(pending)
    return pd.DataFrame(candidates), pd.DataFrame(exits)

def run_daily_scan(frames, signal_provider=None, end_date=None, atr_exit_mult=2.5, portfolio=None, output_dir=None, mode="research", universe_mode="custom", signal_mode="strict_no_lookahead") -> DailyScanReport:
    if mode not in {"research", "paper", "assist"}:
        raise ValueError("mode 必须为 research、paper 或 assist")
    if signal_mode not in {"full_history", "rolling", "strict_no_lookahead"}:
        raise ValueError("signal_mode 必须为 full_history、rolling 或 strict_no_lookahead")
    if not frames:
        raise ValueError("股票数据为空")
    if signal_provider is None and not chanpy_available():
        raise RuntimeError("未安装 chan.py，请设置 CHANPY_PATH 后再执行缠论全量重算")
    latest = _latest_completed_date(frames, end_date)
    candidates, exits = _scan_frames(frames, signal_provider, latest, atr_exit_mult, signal_mode, portfolio)
    plan_rows = []
    for _, row in exits.iterrows():
        plan_rows.append({**row.to_dict(), "action": "sell", "target_weight": 0.0, "reason": row["exit_reason"]})
    exit_codes = set(exits["stock_code"]) if not exits.empty else set()
    for _, row in candidates.iterrows():
        if row["stock_code"] not in exit_codes:
            plan_rows.append({**row.to_dict(), "action": "buy", "reason": row.get("signal_type", "entry_signal")})
    plan = pd.DataFrame(plan_rows)
    lookahead_risk = signal_mode == "full_history"
    report = {"scan_date": str(latest.date()), "universe_mode": universe_mode, "signal_mode": signal_mode, "lookahead_risk": lookahead_risk, "lookahead_warning": "full_history 使用完整历史信号，不能直接作为实盘信号" if lookahead_risk else None, "mode": mode, "stock_count": len(frames), "candidate_count": len(candidates), "exit_count": len(exits), "parameter": {"atr_exit_mult": atr_exit_mult, "atr_period": 14}, "execution_note": "仅生成研究/模拟/实盘辅助计划，不直接调用券商下单。"}
    result = DailyScanReport(candidates, exits, plan, report)
    if output_dir:
        target = Path(output_dir); target.mkdir(parents=True, exist_ok=True)
        candidates.to_csv(target / "daily_signal_candidates.csv", index=False); exits.to_csv(target / "daily_exit_signals.csv", index=False); plan.to_csv(target / "daily_portfolio_plan.csv", index=False)
        (target / "daily_scan_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result
