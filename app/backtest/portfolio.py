"""多股票独立资金回测与等权组合汇总。"""
from dataclasses import dataclass
import pandas as pd
from .config import BacktestConfig
from .contracts import StrategyAdapter
from .runner import scan_atr_exit_mult

@dataclass
class PortfolioScanReport:
    stock_summary: pd.DataFrame
    portfolio_summary: pd.DataFrame
    trades: pd.DataFrame
    equity: pd.DataFrame
    report: dict

def scan_multiple_stocks(stock_codes, data_by_stock, multipliers=None, start_date="2015-01-01", end_date="2025-12-31", config=None, adapter: StrategyAdapter | None = None, output_dir=None):
    config = config or BacktestConfig()
    summaries, trades, curves, warnings = [], [], [], []
    for code in sorted(set(stock_codes)):
        frame = data_by_stock.get(code)
        if frame is None or frame.empty:
            warnings.append({"stock_code": code, "reason": "missing_or_empty_data"})
            continue
        try:
            result = scan_atr_exit_mult(stock_code=code, start_date=start_date, end_date=end_date, multipliers=multipliers, config=config, adapter=adapter, data=frame, evaluate_periods=False)
            item = result.summary.copy(); item.insert(0, "stock_code", code); summaries.append(item)
            if not result.trades.empty: trades.append(result.trades)
            if not result.equity.empty: curves.append(result.equity.assign(stock_code=code))
        except Exception as exc:
            warnings.append({"stock_code": code, "reason": str(exc)})
    if not summaries: raise ValueError(f"没有股票完成回测: {warnings}")
    stock_summary = pd.concat(summaries, ignore_index=True)
    trade_frame = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    curve_frame = pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()
    rows = []
    for mult, group in stock_summary.groupby("atr_exit_mult", sort=True):
        total = int(group.trade_count.sum())
        row = {"atr_exit_mult": mult, "stock_count": int(group.stock_code.nunique()), "total_trade_count": total, "average_trade_count": float(group.trade_count.mean()), "min_trade_stock": str(group.loc[group.trade_count.idxmin(), "stock_code"]), "max_trade_stock": str(group.loc[group.trade_count.idxmax(), "stock_code"]), "concentration_risk": bool(group.trade_count.max() > max(1, total * 0.5))}
        for col in ("total_return", "annualized_return", "max_drawdown", "calmar_ratio", "sharpe_ratio"):
            row[col] = float(group[col].dropna().mean()) if group[col].notna().any() else None
        rows.append(row)
    portfolio_summary = pd.DataFrame(rows)
    equity = pd.DataFrame()
    if not curve_frame.empty:
        for mult, group in curve_frame.groupby("atr_exit_mult"):
            values = group.pivot_table(index="date", columns="stock_code", values="equity").sort_index()
            values = values.div(values.iloc[0]).mean(axis=1) * config.initial_cash
            equity = pd.concat([equity, pd.DataFrame({"date": values.index, "atr_exit_mult": mult, "equity": values.values})], ignore_index=True)
    report = {"stock_codes": sorted(set(stock_codes)), "warnings": warnings, "portfolio_method": "each stock independent equal initial cash, then equal-weight average", "lookahead_risk": adapter.lookahead_risk if adapter else None, "signal_mode": adapter.run_mode if adapter else None}
    if output_dir:
        from pathlib import Path
        target = Path(output_dir); target.mkdir(parents=True, exist_ok=True)
        stock_summary.to_csv(target / "atr_scan_stock_summary.csv", index=False); portfolio_summary.to_csv(target / "atr_scan_portfolio_summary.csv", index=False); trade_frame.to_csv(target / "atr_scan_trades.csv", index=False); equity.to_csv(target / "atr_scan_portfolio_equity.csv", index=False)
    return PortfolioScanReport(stock_summary, portfolio_summary, trade_frame, equity, report)
