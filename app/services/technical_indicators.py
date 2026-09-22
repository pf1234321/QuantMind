# -*- coding: utf-8 -*-
"""技术指标计算服务（按需计算 + 多周期支持）"""
import logging
from datetime import date, timedelta
from typing import Optional, Literal

import pandas as pd
import numpy as np

from app.database import execute_query, execute_many

logger = logging.getLogger(__name__)

PeriodType = Literal["daily", "weekly", "monthly"]


def resample_to_period(df: pd.DataFrame, period: PeriodType) -> pd.DataFrame:
    """将日线数据重采样到周线或月线"""
    if period == "daily":
        return df

    freq_map = {"weekly": "W-FRI", "monthly": "M"}
    freq = freq_map[period]

    # 确保索引是 DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    resampled = df.resample(freq).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'amount': 'sum'
    }).dropna()

    return resampled


def calculate_ma(df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    """计算移动平均线"""
    for period in periods:
        df[f'ma{period}'] = df['close'].rolling(window=period).mean()
    return df


def calculate_ema(df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    """计算指数移动平均"""
    for period in periods:
        df[f'ema{period}'] = df['close'].ewm(span=period, adjust=False).mean()
    return df


def calculate_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    """计算MACD指标"""
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    df['macd_dif'] = ema_fast - ema_slow
    df['macd_dea'] = df['macd_dif'].ewm(span=signal, adjust=False).mean()
    df['macd_bar'] = (df['macd_dif'] - df['macd_dea']) * 2
    return df


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """计算RSI指标"""
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    df[f'rsi{period}'] = 100 - (100 / (1 + rs))
    return df


def calculate_kdj(df: pd.DataFrame, n=9, m1=3, m2=3) -> pd.DataFrame:
    """计算KDJ指标"""
    low_n = df['low'].rolling(window=n).min()
    high_n = df['high'].rolling(window=n).max()
    rsv = (df['close'] - low_n) / (high_n - low_n) * 100

    df['kdj_k'] = rsv.ewm(com=m1-1, adjust=False).mean()
    df['kdj_d'] = df['kdj_k'].ewm(com=m2-1, adjust=False).mean()
    df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']
    return df


def calculate_boll(df: pd.DataFrame, period=20, std_multiplier=2) -> pd.DataFrame:
    """计算布林带"""
    df['boll_mid'] = df['close'].rolling(window=period).mean()
    std = df['close'].rolling(window=period).std()
    df['boll_upper'] = df['boll_mid'] + std_multiplier * std
    df['boll_lower'] = df['boll_mid'] - std_multiplier * std
    return df


def calculate_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算成交量指标"""
    df['vol_ma5'] = df['volume'].rolling(window=5).mean()
    # 量比：当日成交量 / 5日平均成交量
    df['volume_ratio'] = df['volume'] / df['vol_ma5']
    return df


def calculate_atr(df: pd.DataFrame, period=14) -> pd.DataFrame:
    """计算ATR（平均真实波幅）"""
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(window=period).mean()
    return df


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算所有技术指标"""
    df = calculate_ma(df, [5, 20, 60])
    df = calculate_macd(df)
    df = calculate_rsi(df, 14)
    df = calculate_kdj(df)
    df = calculate_boll(df)
    df = calculate_volume_indicators(df)
    df = calculate_atr(df)
    return df


def sync_technical_indicators(
    stock_codes: Optional[list] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: PeriodType = "daily",
    force_refresh: bool = False
) -> dict:
    """同步技术指标计算（支持多周期）"""

    # 获取股票列表
    if stock_codes is None:
        stock_codes = [r["stock_code"] for r in execute_query(
            "SELECT DISTINCT stock_code FROM trade_stock_status LIMIT 100"
        )]

    total_written = 0
    failed_stocks = []

    for code in stock_codes:
        try:
            # 确定计算起始日期
            if start_date is None and not force_refresh:
                latest = execute_query(
                    "SELECT MAX(trade_date) AS latest FROM trade_technical_summary "
                    "WHERE stock_code=%s AND period=%s",
                    (code, period)
                )
                if latest and latest[0]['latest']:
                    calc_start = (latest[0]['latest'] - timedelta(days=100)).strftime("%Y%m%d")
                else:
                    calc_start = "20200101"
            else:
                calc_start = start_date or "20200101"

            calc_end = end_date or date.today().strftime("%Y%m%d")

            # 获取K线数据（需要更多历史数据用于指标计算）
            kline_start = (pd.to_datetime(calc_start) - timedelta(days=200)).strftime("%Y%m%d")
            klines = execute_query(
                """
                SELECT stock_code, trade_date, open_price, high_price, low_price,
                       close_price, volume, amount
                FROM trade_stock_daily
                WHERE stock_code=%s AND trade_date>=%s
                ORDER BY trade_date ASC
                """,
                (code, kline_start)
            )

            if not klines or len(klines) < 60:
                logger.warning(f"股票 {code} K线数据不足，跳过")
                continue

            # 转为DataFrame
            df = pd.DataFrame(klines)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.set_index('trade_date')
            df = df.rename(columns={
                'open_price': 'open',
                'high_price': 'high',
                'low_price': 'low',
                'close_price': 'close'
            })

            # 转换 Decimal 为 float
            numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = df[col].astype(float)

            # 重采样到目标周期
            df = resample_to_period(df, period)

            if df.empty or len(df) < 60:
                logger.warning(f"股票 {code} {period} 数据不足，跳过")
                continue

            # 计算所有技术指标
            df = calculate_all_indicators(df)

            # 过滤到目标日期范围（转换为 datetime 类型）
            df = df[df.index >= pd.to_datetime(calc_start)]

            # 准备插入数据
            rows = []
            for idx, row in df.iterrows():
                rows.append((
                    code,
                    idx.strftime("%Y-%m-%d"),
                    period,
                    row.get('ma5'), row.get('ma20'), row.get('ma60'),
                    row.get('rsi14'),
                    row.get('macd_dif'), row.get('macd_dea'), row.get('macd_bar'),
                    row.get('kdj_k'), row.get('kdj_d'), row.get('kdj_j'),
                    row.get('atr14'),
                    row.get('volume_ratio')
                ))

            if rows:
                insert_sql = """
                INSERT INTO trade_technical_summary
                (stock_code, trade_date, period, ma5, ma20, ma60, rsi14,
                 macd_dif, macd_dea, macd_bar, kdj_k, kdj_d, kdj_j, atr14, volume_ratio)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                ma5=VALUES(ma5), ma20=VALUES(ma20), ma60=VALUES(ma60), rsi14=VALUES(rsi14),
                macd_dif=VALUES(macd_dif), macd_dea=VALUES(macd_dea), macd_bar=VALUES(macd_bar),
                kdj_k=VALUES(kdj_k), kdj_d=VALUES(kdj_d), kdj_j=VALUES(kdj_j),
                atr14=VALUES(atr14), volume_ratio=VALUES(volume_ratio)
                """
                execute_many(insert_sql, rows)
                total_written += len(rows)
                logger.info(f"股票 {code} {period} 技术指标计算完成，写入 {len(rows)} 条")

        except Exception as exc:
            failed_stocks.append({"stock_code": code, "error": str(exc)})
            logger.exception(f"股票 {code} {period} 技术指标计算失败")

    return {
        "period": period,
        "written": total_written,
        "failed": len(failed_stocks),
        "total": len(stock_codes),
        "failed_stocks": failed_stocks
    }


def get_latest_indicators(stock_code: str, period: PeriodType = "daily", limit: int = 1) -> list[dict]:
    """获取最新的技术指标"""
    rows = execute_query(
        """
        SELECT * FROM trade_technical_summary
        WHERE stock_code=%s AND period=%s
        ORDER BY trade_date DESC
        LIMIT %s
        """,
        (stock_code, period, limit)
    )
    return rows
