import importlib.util
import sys
from pathlib import Path
import pandas as pd

from .contracts import BacktestResult, StrategyAdapter
from .trade_tracking import pair_completed_orders


class CourseAdapterError(RuntimeError):
    pass


def load_course_adapter(module_path: str) -> StrategyAdapter:
    path = Path(module_path)
    if not path.exists():
        raise CourseAdapterError(f"课程模块不存在: {module_path}")
    spec = importlib.util.spec_from_file_location("quantmind_course_adapter", path)
    if spec is None or spec.loader is None:
        raise CourseAdapterError(f"无法加载课程模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    course_dir = str(path.parent)
    sys.path.insert(0, course_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(course_dir)
    runner = getattr(module, "run_parameter_backtest", None)
    if callable(runner):
        return StrategyAdapter(run=runner, source_description=str(path), run_mode="full_history", lookahead_risk=True)

    required = ("run_chan", "build_signal_df", "ChanAtrEnhancedStrategy", "ChanPandasData", "run_and_report")
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise CourseAdapterError(
            "课程模块缺少参数扫描所需入口: " + ", ".join(missing)
            + "; 需要 run_parameter_backtest(...) 或完整课程策略组件"
        )

    signal_cache = {}

    def compatible_runner(df, atr_exit_mult, config):
        cache_key = (id(df), tuple(df.index), tuple(df.columns))
        if cache_key not in signal_cache:
            chan_data = module.run_chan(df, symbol="scan")
            signal_cache[cache_key] = module.build_signal_df(df, chan_data)
        signal_df = signal_cache[cache_key].copy()
        result = module.run_and_report(
            module.ChanAtrEnhancedStrategy,
            stock_code=None,
            start_date=None,
            end_date=None,
            label=f"ATR×{atr_exit_mult:g}",
            plot=False,
            quiet=True,
            df=signal_df,
            data_class=module.ChanPandasData,
            atr_exit_mult=float(atr_exit_mult),
            atr_period=config.atr_period,
            breakeven_pct=config.breakeven_pct,
            lock_profit_pct=config.lock_profit_pct,
            lock_amount_pct=config.lock_amount_pct,
        )
        equity = pd.Series(
            {pd.Timestamp(item["date"]): float(item["nav"]) for item in result.get("nav", [])},
            dtype=float,
        ).sort_index()
        trades, open_trades = pair_completed_orders(result.get("trades", []), atr_exit_mult=float(atr_exit_mult))
        return BacktestResult(equity=equity, trades=trades + open_trades, metadata={"course_metrics": result, "open_trades": open_trades})

    return StrategyAdapter(
        run=compatible_runner,
        source_description=str(path),
        run_mode="full_history",
        lookahead_risk=True,
    )


def _pair_course_trades(order_log: list[dict]) -> list[dict]:
    """将课程 data_loader 的买卖订单日志配对成参数扫描交易明细。"""
    open_trade = None
    trades = []
    for order in order_log:
        if order.get("type") == "BUY":
            open_trade = {
                "entry_date": pd.Timestamp(order["date"]),
                "entry_price": float(order["price"]),
                "entry_size": int(order.get("size", 0)),
            }
        elif order.get("type") == "SELL" and open_trade is not None:
            entry_price = open_trade["entry_price"]
            exit_price = float(order["price"])
            entry_date = open_trade["entry_date"]
            exit_date = pd.Timestamp(order["date"])
            trades.append({
                **open_trade,
                "exit_date": exit_date,
                "exit_price": exit_price,
                "return_pct": exit_price / entry_price - 1 if entry_price else 0.0,
                "holding_days": (exit_date - entry_date).days,
                "exit_reason": "unknown_course_exit",
            })
            open_trade = None
    return trades
