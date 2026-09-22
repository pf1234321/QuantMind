from dataclasses import dataclass
import json
from pathlib import Path
import pandas as pd

from app.database import execute_query
from .config import BacktestConfig
from .contracts import BacktestResult, StrategyAdapter
from .data import load_daily_bars
from .metrics import calculate_metrics
from .selection import rank_results, select_stable
from .validation import actual_range, validate_multipliers


@dataclass
class ScanReport:
    summary: pd.DataFrame
    trades: pd.DataFrame
    equity: pd.DataFrame
    report: dict


def _buy_hold(frame: pd.DataFrame) -> float:
    return float(frame.close.iloc[-1] / frame.close.iloc[0] - 1)


def _split_ranges(frame: pd.DataFrame, splits: dict | None) -> dict:
    requested = splits or {
        "train": ("2022-01-01", "2024-06-30"),
        "validation": ("2024-07-01", "2025-03-31"),
        "test": ("2025-04-01", "2025-12-31"),
    }
    output = {}
    for name, bounds in requested.items():
        start, end = bounds
        mask = (frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))
        subset = frame.loc[mask]
        output[name] = {"requested": [start, end], "actual": [str(subset.index.min().date()), str(subset.index.max().date())] if not subset.empty else None}
    return output


def scan_atr_exit_mult(stock_code="300750", start_date="2020-01-01", end_date="2025-12-31", multipliers=None, range_start=None, range_end=None, step=None, splits=None, config=None, output_dir=None, adapter: StrategyAdapter | None = None, data=None, evaluate_periods=True) -> ScanReport:
    config = config or BacktestConfig()
    values = validate_multipliers(multipliers, range_start, range_end, step)
    if adapter is None:
        raise ValueError("必须显式提供策略 adapter；请使用 build_internal_adapter() 或 load_course_adapter()")
    frame = data.copy() if data is not None else load_daily_bars(stock_code, start_date, end_date, execute_query)
    actual_start, actual_end = actual_range(frame, start_date, end_date)
    frame = frame.loc[actual_start:actual_end].copy()
    buy_hold = _buy_hold(frame)
    rows, trade_rows, equity_rows = [], [], []
    for multiplier in values:
        raw = adapter.run(frame.copy(), multiplier, config)
        if not isinstance(raw, BacktestResult):
            raise TypeError("adapter 必须返回 BacktestResult")
        metrics, drawdown = calculate_metrics(raw.equity, raw.trades, buy_hold, config, actual_start, actual_end)
        row = {"atr_exit_mult": multiplier, **metrics, "lookahead_risk": adapter.lookahead_risk, "signal_mode": adapter.run_mode, "is_baseline": multiplier == 2.5}
        rows.append(row)
        for trade in raw.trades:
            trade_rows.append({"atr_exit_mult": multiplier, "stock_code": stock_code, **trade})
        for dt, value in raw.equity.items():
            equity_rows.append({"atr_exit_mult": multiplier, "date": pd.Timestamp(dt), "equity": float(value), "drawdown": float(drawdown.loc[dt])})
    summary = pd.DataFrame(rows)
    selection = select_stable(summary, config.min_trades, config.max_acceptable_drawdown)
    summary["confidence"] = summary["trade_count"].map(lambda count: "very_low" if count < 3 else "low" if count < 10 else "medium" if count < 30 else "higher")
    rankings = rank_results(summary)
    report = {"stock_code": stock_code, "requested_range": [start_date, end_date], "actual_range": [actual_start, actual_end], "lookahead_risk": adapter.lookahead_risk, "signal_mode": adapter.run_mode, "rankings": rankings, "selection": selection, "baseline": 2.5, "splits": _split_ranges(frame, splits), "warning": "完整历史缠论信号可能包含前视偏差，结果不可直接视为实盘结论。" if adapter.lookahead_risk else None}
    result = ScanReport(summary, pd.DataFrame(trade_rows), pd.DataFrame(equity_rows), report)
    period_reports = {}
    if not evaluate_periods:
        return result
    for period_name, bounds in (splits or {"train": ("2022-01-01", "2024-06-30"), "validation": ("2024-07-01", "2025-03-31"), "test": ("2025-04-01", "2025-12-31")}).items():
        period_frame = frame.loc[(frame.index >= pd.Timestamp(bounds[0])) & (frame.index <= pd.Timestamp(bounds[1]))]
        if period_frame.empty:
            period_reports[period_name] = {"actual_range": None, "summary": []}
            continue
        period = scan_atr_exit_mult(
            stock_code=stock_code, start_date=str(period_frame.index.min().date()), end_date=str(period_frame.index.max().date()),
            multipliers=values, config=config, adapter=adapter, data=period_frame, evaluate_periods=False,
        )
        period_reports[period_name] = {"actual_range": [str(period_frame.index.min().date()), str(period_frame.index.max().date())], "summary": period.summary.to_dict(orient="records")}
        period_columns = period.summary.set_index("atr_exit_mult").add_prefix(f"{period_name}_")
        result.summary = result.summary.join(period_columns, on="atr_exit_mult")
    result.report["period_reports"] = period_reports
    if output_dir:
        _write_outputs(result, Path(output_dir))
    return result


def _write_outputs(result: ScanReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result.summary.to_csv(output_dir / "atr_scan_summary.csv", index=False)
    result.trades.to_csv(output_dir / "atr_scan_trades.csv", index=False)
    result.equity.to_csv(output_dir / "atr_scan_equity.csv", index=False)
    if not result.trades.empty:
        reasons = result.trades[result.trades.get("exit_date").notna()].groupby(["atr_exit_mult", "exit_reason"], dropna=False).size().reset_index(name="trade_count")
    else:
        reasons = pd.DataFrame(columns=["atr_exit_mult", "exit_reason", "trade_count"])
    reasons.to_csv(output_dir / "atr_scan_exit_reason_summary.csv", index=False)
    _plot_comparison(result, output_dir / "atr_scan_comparison.png")
    (output_dir / "atr_scan_report.json").write_text(json.dumps(result.report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _plot_comparison(result: ScanReport, target: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("生成回测图需要安装 matplotlib") from exc
    selected = {2.5}
    recommended = result.report.get("selection", {}).get("recommended")
    if recommended is not None:
        selected.add(float(recommended))
    interval = result.report.get("selection", {}).get("interval")
    if interval:
        selected.add(float(interval[0] + (interval[1] - interval[0]) / 2))
    selected = [value for value in sorted(selected) if value in set(result.equity.atr_exit_mult)]
    if not selected:
        return
    figure, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for multiplier in selected:
        curve = result.equity[result.equity.atr_exit_mult == multiplier].sort_values("date")
        axes[0].plot(curve.date, curve.equity, label=f"ATR×{multiplier:g}")
        axes[1].plot(curve.date, curve.drawdown, label=f"ATR×{multiplier:g}")
    axes[0].set_ylabel("Equity")
    axes[1].set_ylabel("Drawdown")
    axes[1].set_xlabel("Date")
    axes[0].legend()
    axes[1].legend()
    axes[0].grid(alpha=0.3)
    axes[1].grid(alpha=0.3)
    figure.tight_layout()
    figure.savefig(target, dpi=150)
    plt.close(figure)
