# -*- coding: utf-8 -*-
"""技术指标策略回测服务"""
import logging
import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Optional, Literal
from dataclasses import dataclass

import pandas as pd

from app.database import execute_query, execute_update
from app.backtest.config import BacktestConfig
from app.backtest.contracts import BacktestResult, StrategyAdapter
from app.backtest.data import load_daily_bars
from app.backtest.metrics import calculate_metrics
from app.services.technical_indicators import (
    calculate_ma, calculate_macd, calculate_rsi,
    calculate_kdj, calculate_boll, resample_to_period
)

logger = logging.getLogger(__name__)

StrategyType = Literal["ma_cross", "macd", "rsi", "kdj", "boll", "ma_macd_combined", "triple_combined"]


@dataclass
class TechnicalStrategy:
    """技术指标策略配置"""
    strategy_type: StrategyType
    stop_loss_pct: float = 0.08
    take_profit_pct: float = 0.20
    position_pct: float = 0.95


def apply_ma_cross_signals(df: pd.DataFrame) -> pd.DataFrame:
    """均线交叉策略信号"""
    df = calculate_ma(df.copy(), [5, 20])
    df['buy_signal'] = (df['ma5'] > df['ma20']) & (df['ma5'].shift(1) <= df['ma20'].shift(1))
    df['sell_signal'] = (df['ma5'] < df['ma20']) & (df['ma5'].shift(1) >= df['ma20'].shift(1))
    return df


def apply_macd_signals(df: pd.DataFrame) -> pd.DataFrame:
    """MACD 金叉死叉策略"""
    df = calculate_macd(df.copy())
    df['buy_signal'] = (df['macd_dif'] > df['macd_dea']) & (df['macd_dif'].shift(1) <= df['macd_dea'].shift(1))
    df['sell_signal'] = (df['macd_dif'] < df['macd_dea']) & (df['macd_dif'].shift(1) >= df['macd_dea'].shift(1))
    return df


def apply_rsi_signals(df: pd.DataFrame) -> pd.DataFrame:
    """RSI 超买超卖策略"""
    df = calculate_rsi(df.copy(), 14)
    df['buy_signal'] = df['rsi14'] < 30  # 超卖
    df['sell_signal'] = df['rsi14'] > 70  # 超买
    return df


def apply_kdj_signals(df: pd.DataFrame) -> pd.DataFrame:
    """KDJ 超买超卖策略"""
    df = calculate_kdj(df.copy())
    df['buy_signal'] = df['kdj_j'] < 20  # 超卖
    df['sell_signal'] = df['kdj_j'] > 80  # 超买
    return df


def apply_boll_signals(df: pd.DataFrame) -> pd.DataFrame:
    """布林带突破策略"""
    df = calculate_boll(df.copy())
    df['buy_signal'] = df['close'] < df['boll_lower']  # 突破下轨
    df['sell_signal'] = df['close'] > df['boll_upper']  # 突破上轨
    return df


def apply_ma_macd_combined_signals(df: pd.DataFrame) -> pd.DataFrame:
    """均线 + MACD 组合策略"""
    df = calculate_ma(df.copy(), [5, 20, 60])
    df = calculate_macd(df)

    # 买入：均线多头排列 + MACD金叉
    ma_bullish = (df['ma5'] > df['ma20']) & (df['ma20'] > df['ma60'])
    macd_golden = (df['macd_dif'] > df['macd_dea']) & (df['macd_dif'].shift(1) <= df['macd_dea'].shift(1))
    df['buy_signal'] = ma_bullish & macd_golden

    # 卖出：均线死叉或MACD死叉
    ma_death = (df['ma5'] < df['ma20']) & (df['ma5'].shift(1) >= df['ma20'].shift(1))
    macd_death = (df['macd_dif'] < df['macd_dea']) & (df['macd_dif'].shift(1) >= df['macd_dea'].shift(1))
    df['sell_signal'] = ma_death | macd_death

    return df


def apply_triple_combined_signals(df: pd.DataFrame) -> pd.DataFrame:
    """三重组合策略：均线 + MACD + RSI"""
    df = calculate_ma(df.copy(), [5, 20])
    df = calculate_macd(df)
    df = calculate_rsi(df, 14)

    # 买入：均线金叉 + MACD金叉 + RSI不超买
    ma_golden = (df['ma5'] > df['ma20']) & (df['ma5'].shift(1) <= df['ma20'].shift(1))
    macd_golden = (df['macd_dif'] > df['macd_dea']) & (df['macd_dif'].shift(1) <= df['macd_dea'].shift(1))
    rsi_ok = df['rsi14'] < 70
    df['buy_signal'] = ma_golden & macd_golden & rsi_ok

    # 卖出：任一指标出现卖出信号
    ma_death = (df['ma5'] < df['ma20']) & (df['ma5'].shift(1) >= df['ma20'].shift(1))
    macd_death = (df['macd_dif'] < df['macd_dea']) & (df['macd_dif'].shift(1) >= df['macd_dea'].shift(1))
    rsi_over = df['rsi14'] > 80
    df['sell_signal'] = ma_death | macd_death | rsi_over

    return df


STRATEGY_FUNCTIONS = {
    'ma_cross': apply_ma_cross_signals,
    'macd': apply_macd_signals,
    'rsi': apply_rsi_signals,
    'kdj': apply_kdj_signals,
    'boll': apply_boll_signals,
    'ma_macd_combined': apply_ma_macd_combined_signals,
    'triple_combined': apply_triple_combined_signals,
}


def run_technical_strategy(
    frame: pd.DataFrame,
    strategy: TechnicalStrategy,
    config: BacktestConfig
) -> BacktestResult:
    """执行技术指标策略回测"""

    # 应用策略信号
    signal_func = STRATEGY_FUNCTIONS.get(strategy.strategy_type)
    if not signal_func:
        raise ValueError(f"不支持的策略类型: {strategy.strategy_type}")

    df = signal_func(frame.copy())

    # 回测执行
    cash = float(config.initial_cash)
    shares = 0.0
    entry_price = None
    entry_date = None
    trades = []
    equity = []

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i]
        close = float(row['close'])

        # 买入信号
        if shares == 0 and row.get('buy_signal', False) and i + 1 < len(df):
            next_open = float(df.iloc[i + 1]['open']) * (1 + config.slippage)
            shares = cash * strategy.position_pct / next_open
            fee = shares * next_open * config.commission
            cash -= shares * next_open + fee
            entry_price = next_open
            entry_date = df.index[i + 1]

        # 卖出逻辑
        elif shares > 0:
            stop_loss = entry_price * (1 - strategy.stop_loss_pct)
            take_profit = entry_price * (1 + strategy.take_profit_pct)

            exit_reason = None
            if close <= stop_loss:
                exit_reason = 'stop_loss'
            elif close >= take_profit:
                exit_reason = 'take_profit'
            elif row.get('sell_signal', False):
                exit_reason = 'signal_exit'

            if exit_reason and i + 1 < len(df):
                exit_price = float(df.iloc[i + 1]['open']) * (1 - config.slippage)
                fee = shares * exit_price * config.commission
                cash += shares * exit_price - fee

                gross = (exit_price - entry_price) * shares
                net = gross - fee

                trades.append({
                    'entry_date': entry_date,
                    'entry_price': entry_price,
                    'exit_date': df.index[i + 1],
                    'exit_price': exit_price,
                    'return_pct': exit_price / entry_price - 1,
                    'net_return_pct': net / (entry_price * shares),
                    'holding_days': (df.index[i + 1] - entry_date).days,
                    'exit_reason': exit_reason,
                    'gross_profit': gross,
                    'fee': fee,
                    'net_profit': net
                })
                shares = 0.0

        equity.append(cash + shares * close)

    return BacktestResult(
        pd.Series(equity, index=df.index),
        trades,
        {'strategy': strategy.strategy_type}
    )


def ensure_kline_data_updated(stock_code: str, end_date: str) -> bool:
    """确保K线数据更新到指定日期，如有缺失则自动补充。

    Args:
        stock_code: 股票代码
        end_date: 需要的截止日期 (YYYY-MM-DD 或 YYYYMMDD)

    Returns:
        bool: 是否成功更新数据
    """
    from app.services.kline_sync import sync_kline

    # 标准化日期格式
    end_date_str = end_date.replace('-', '')[:8]
    end_date_obj = datetime.strptime(end_date_str, '%Y%m%d').date()

    # 查询数据库中该股票最新的K线日期
    latest = execute_query(
        "SELECT MAX(trade_date) AS latest_date FROM trade_stock_daily WHERE stock_code=%s",
        (stock_code,)
    )

    if not latest or not latest[0]['latest_date']:
        # 没有数据，从默认起始日期同步
        logger.info(f"股票 {stock_code} 无K线数据，开始全量同步")
        sync_kline(stock_codes=[stock_code], end_date=end_date_str)
        return True

    latest_date = latest[0]['latest_date']

    # 计算数据缺失天数
    days_missing = (end_date_obj - latest_date).days

    # 如果数据已是最新或只差1天（可能是非交易日），不需要更新
    if days_missing <= 1:
        logger.debug(f"股票 {stock_code} K线数据已是最新 (截止: {latest_date})")
        return True

    # 如果缺失超过1天，增量同步
    logger.info(f"股票 {stock_code} K线数据需要更新: 当前截止 {latest_date}，需要到 {end_date_obj}，缺失 {days_missing} 天")

    try:
        # 从最新日期的下一天开始同步
        start_sync_date = (latest_date + timedelta(days=1)).strftime('%Y%m%d')
        sync_kline(stock_codes=[stock_code], start_date=start_sync_date, end_date=end_date_str)
        logger.info(f"股票 {stock_code} K线数据更新完成")
        return True
    except Exception as e:
        logger.error(f"股票 {stock_code} K线数据更新失败: {e}")
        return False


def batch_backtest_strategies(
    stock_codes: list[str],
    strategy_types: list[StrategyType],
    start_date: str,
    end_date: str,
    period: str = "daily",
    save_to_db: bool = True
) -> list[dict]:
    """批量回测技术指标策略"""

    results = []
    config = BacktestConfig()
    backtest_id = hashlib.md5(f"{','.join(stock_codes)}_{start_date}_{end_date}".encode()).hexdigest()[:16]

    for code in stock_codes:
        try:
            # 确保K线数据更新到指定的截止日期
            logger.info(f"检查股票 {code} 的K线数据完整性")
            ensure_kline_data_updated(code, end_date)

            # 加载K线数据
            frame = load_daily_bars(code, start_date, end_date, execute_query)

            if frame.empty or len(frame) < 60:
                logger.warning(f"股票 {code} K线数据不足")
                continue

            # 转换周期
            if period != "daily":
                frame = resample_to_period(frame, period)

            buy_hold = float(frame.close.iloc[-1] / frame.close.iloc[0] - 1)

            for strategy_type in strategy_types:
                try:
                    # 执行回测
                    strategy = TechnicalStrategy(strategy_type=strategy_type)
                    backtest_result = run_technical_strategy(frame, strategy, config)

                    # 计算指标
                    metrics, drawdown = calculate_metrics(
                        backtest_result.equity,
                        backtest_result.trades,
                        buy_hold,
                        config,
                        start_date,
                        end_date
                    )

                    result = {
                        'backtest_id': backtest_id,
                        'stock_code': code,
                        'strategy_type': strategy_type,
                        'period': period,
                        'start_date': start_date,
                        'end_date': end_date,
                        'metrics': metrics,
                        'trade_count': len(backtest_result.trades),
                        'buy_hold_return': buy_hold
                    }

                    results.append(result)

                    # 保存到数据库
                    if save_to_db:
                        _save_backtest_result(result, strategy)
                        _save_trade_details(result['backtest_id'], code, strategy_type, period, backtest_result.trades)

                    logger.info(
                        f"回测完成: {code} {strategy_type} {period} "
                        f"年化收益={metrics['annualized_return']:.2%} "
                        f"夏普={metrics.get('sharpe_ratio', 0):.2f}"
                    )

                except Exception as e:
                    logger.exception(f"策略回测失败: {code} {strategy_type}")

        except Exception as e:
            logger.exception(f"加载数据失败: {code}")

    return results


def _save_backtest_result(result: dict, strategy: TechnicalStrategy):
    """保存回测结果到数据库"""
    metrics = result['metrics']

    execute_update(
        """
        INSERT INTO trade_technical_backtest
        (backtest_id, stock_code, strategy_type, period, start_date, end_date,
         total_return, annualized_return, max_drawdown, sharpe_ratio, calmar_ratio,
         trade_count, win_rate, profit_loss_ratio, avg_holding_days,
         strategy_params_json, metrics_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        total_return=VALUES(total_return), annualized_return=VALUES(annualized_return),
        max_drawdown=VALUES(max_drawdown), sharpe_ratio=VALUES(sharpe_ratio),
        calmar_ratio=VALUES(calmar_ratio), trade_count=VALUES(trade_count),
        win_rate=VALUES(win_rate), profit_loss_ratio=VALUES(profit_loss_ratio),
        avg_holding_days=VALUES(avg_holding_days), metrics_json=VALUES(metrics_json)
        """,
        (
            result['backtest_id'],
            result['stock_code'],
            result['strategy_type'],
            result['period'],
            result['start_date'],
            result['end_date'],
            metrics.get('total_return'),
            metrics.get('annualized_return'),
            metrics.get('max_drawdown'),
            metrics.get('sharpe_ratio'),
            metrics.get('calmar_ratio'),
            metrics.get('trade_count'),
            metrics.get('win_rate'),
            metrics.get('profit_loss_ratio'),
            metrics.get('average_holding_days'),
            json.dumps({
                'stop_loss_pct': strategy.stop_loss_pct,
                'take_profit_pct': strategy.take_profit_pct
            }),
            json.dumps(metrics, ensure_ascii=False, default=str)
        )
    )


def _save_trade_details(backtest_id: str, stock_code: str, strategy_type: str, period: str, trades: list):
    """保存交易明细到数据库"""
    if not trades:
        return

    from app.database import execute_many
    import pandas as pd

    rows = []
    for trade in trades:
        # 兼容字典和对象两种格式
        if isinstance(trade, dict):
            entry_date = pd.to_datetime(trade['entry_date']).strftime("%Y-%m-%d")
            exit_date = pd.to_datetime(trade['exit_date']).strftime("%Y-%m-%d")
            entry_price = float(trade['entry_price'])
            exit_price = float(trade['exit_price'])
            return_pct = float(trade['return_pct'])
            profit_loss = float(trade.get('net_profit', trade.get('profit_loss', 0)))
            holding_days = int(trade['holding_days'])
            exit_reason = trade.get('exit_reason', 'manual_or_other')

            # 计算持仓市值（假设10万初始资金）
            position_value = 100000.0
            shares = int(position_value / entry_price)
        else:
            entry_date = trade.entry_date.strftime("%Y-%m-%d")
            exit_date = trade.exit_date.strftime("%Y-%m-%d")
            entry_price = float(trade.entry_price)
            exit_price = float(trade.exit_price)
            shares = int(trade.shares)
            position_value = float(trade.position_value)
            return_pct = float(trade.return_pct)
            profit_loss = float(trade.profit_loss)
            holding_days = int(trade.holding_days)
            exit_reason = trade.exit_reason or 'manual_or_other'

        rows.append((
            backtest_id,
            stock_code,
            strategy_type,
            period,
            entry_date,
            exit_date,
            entry_price,
            exit_price,
            shares,
            position_value,
            return_pct,
            profit_loss,
            holding_days,
            exit_reason,
            f'{strategy_type} 买入信号',
            f'{exit_reason} 信号'
        ))

    if rows:
        execute_many(
            """
            INSERT INTO trade_technical_trades
            (backtest_id, stock_code, strategy_type, period, entry_date, exit_date,
             entry_price, exit_price, shares, position_value, return_pct, profit_loss,
             holding_days, exit_reason, entry_signal, exit_signal)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
             entry_price=VALUES(entry_price), exit_price=VALUES(exit_price),
             shares=VALUES(shares), position_value=VALUES(position_value),
             return_pct=VALUES(return_pct), profit_loss=VALUES(profit_loss),
             holding_days=VALUES(holding_days), exit_reason=VALUES(exit_reason),
             entry_signal=VALUES(entry_signal), exit_signal=VALUES(exit_signal)
            """,
            rows
        )


def get_best_strategies(
    stock_code: Optional[str] = None,
    min_sharpe: float = 1.0,
    min_trades: int = 10,
    limit: int = 20
) -> list[dict]:
    """获取最佳策略（按年化收益排序）"""

    sql = """
        SELECT * FROM trade_technical_backtest
        WHERE trade_count >= %s
    """
    params = [min_trades]

    if stock_code:
        sql += " AND stock_code=%s"
        params.append(stock_code)

    if min_sharpe:
        sql += " AND sharpe_ratio >= %s"
        params.append(min_sharpe)

    sql += " ORDER BY annualized_return DESC LIMIT %s"
    params.append(limit)

    return execute_query(sql, params)


def compare_strategies_for_stock(stock_code: str, period: str = "daily") -> dict:
    """对比单只股票的所有策略表现"""

    results = execute_query(
        """
        SELECT strategy_type, annualized_return, max_drawdown, sharpe_ratio,
               win_rate, trade_count, avg_holding_days
        FROM trade_technical_backtest
        WHERE stock_code=%s AND period=%s
        ORDER BY annualized_return DESC
        """,
        (stock_code, period)
    )

    if not results:
        return {"stock_code": stock_code, "strategies": []}

    # 找出最佳策略
    best = results[0]

    return {
        "stock_code": stock_code,
        "period": period,
        "best_strategy": best['strategy_type'],
        "best_return": best['annualized_return'],
        "strategies": results,
        "summary": {
            "total_tested": len(results),
            "avg_return": sum(r['annualized_return'] or 0 for r in results) / len(results) if results else 0
        }
    }


def get_trade_details(
    backtest_id: str,
    stock_code: str,
    strategy_type: str,
    period: str = "daily"
) -> list[dict]:
    """获取回测的交易明细"""

    results = execute_query(
        """
        SELECT * FROM trade_technical_trades
        WHERE backtest_id=%s AND stock_code=%s AND strategy_type=%s AND period=%s
        ORDER BY entry_date ASC
        """,
        (backtest_id, stock_code, strategy_type, period)
    )

    return results

