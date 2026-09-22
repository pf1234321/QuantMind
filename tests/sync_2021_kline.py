# -*- coding: utf-8 -*-
"""多线程补齐 2021 年全量股票日 K 线。

数据来自 Tushare daily 和 adj_factor，价格转换为前复权口径后写入
trade_stock_daily。只插入数据库中不存在的 (stock_code, trade_date)，不覆盖已有数据。

运行：
    TUSHARE_TOKEN=your_token python tests/sync_2021_kline.py

可选环境变量：
- KLINE_SYNC_WRITE=0：只检查，不写入数据库
- KLINE_MAX_WORKERS=4：并发线程数，建议不要设置过大
- KLINE_STOCK_CODES=000001,600000：只同步指定股票
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from app.database import execute_many, execute_query

try:
    import tushare as ts
except ImportError:
    ts = None


START_DATE = "20220101"
END_DATE = "20260824"
MAX_WORKERS = max(1, int(os.getenv("KLINE_MAX_WORKERS", "4")))


def load_token() -> str:
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if token:
        return token
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "TUSHARE_TOKEN":
            return value.strip().strip("\"'")
    return ""


def stock_codes() -> tuple[list[str], str]:
    configured = os.getenv("KLINE_STOCK_CODES", "").strip()
    if configured:
        return sorted({item.strip().upper() for item in configured.split(",") if item.strip()}), "KLINE_STOCK_CODES"

    rows = execute_query(
        "SELECT DISTINCT stock_code FROM trade_stock_status "
        "WHERE stock_code IS NOT NULL AND stock_code <> '' ORDER BY stock_code"
    )
    codes = [str(row["stock_code"]).strip().upper() for row in rows if row.get("stock_code")]
    return codes, "trade_stock_status"


def tushare_code(stock_code: str) -> str:
    code = stock_code.upper().strip()
    if "." in code:
        return code
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("8", "4")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def database_code(stock_code: str) -> str:
    return stock_code.split(".", 1)[0]


def existing_dates(stock_code: str) -> set[str]:
    rows = execute_query(
        "SELECT trade_date FROM trade_stock_daily "
        "WHERE stock_code=%s AND trade_date BETWEEN %s AND %s",
        (database_code(stock_code), START_DATE, END_DATE),
    )
    return {str(row["trade_date"])[:10].replace("-", "") for row in rows}


def to_float(value):
    return None if pd.isna(value) else float(value)


def fetch_daily(pro, stock_code: str) -> pd.DataFrame:
    ts_code = tushare_code(stock_code)
    daily = pro.daily(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE)
    if daily is None or daily.empty:
        return pd.DataFrame()
    daily = daily.copy()
    daily["trade_date"] = daily["trade_date"].astype(str)
    daily = daily.sort_values("trade_date")

    factors = pro.adj_factor(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE)
    if factors is None or factors.empty:
        raise RuntimeError("未返回 adj_factor，停止写入以避免混入未复权数据")
    factors = factors[["trade_date", "adj_factor"]].copy()
    factors["trade_date"] = factors["trade_date"].astype(str)
    daily = daily.merge(factors, on="trade_date", how="inner", validate="one_to_one")
    if daily.empty:
        raise RuntimeError("daily 与 adj_factor 没有匹配的交易日")

    factor = daily["adj_factor"].astype(float)
    latest_factor = factor.iloc[-1]
    for column in ("open", "high", "low", "close"):
        daily[column] = daily[column].astype(float) * factor / latest_factor
    daily["volume"] = daily["vol"].astype(float) * 100
    daily["amount"] = daily["amount"].astype(float) * 1000

    basics = pro.daily_basic(
        ts_code=ts_code,
        start_date=START_DATE,
        end_date=END_DATE,
        fields="ts_code,trade_date,turnover_rate",
    )
    if basics is None or basics.empty or "turnover_rate" not in basics:
        raise RuntimeError("Tushare daily_basic 未返回 turnover_rate，停止写入")
    basics = basics[["trade_date", "turnover_rate"]].copy()
    basics["trade_date"] = basics["trade_date"].astype(str)
    daily = daily.merge(basics, on="trade_date", how="left", validate="one_to_one")
    if daily["turnover_rate"].isna().any():
        raise RuntimeError("daily_basic 的 turnover_rate 与日 K 交易日未完全匹配，停止写入")
    return daily


def missing_rows(frame: pd.DataFrame, stock_code: str, dates: set[str]) -> list[tuple]:
    rows = []
    for item in frame.itertuples(index=False):
        trade_date = str(item.trade_date)
        if trade_date in dates:
            continue
        rows.append(
            (
                database_code(stock_code),
                datetime.strptime(trade_date, "%Y%m%d").date(),
                to_float(item.open),
                to_float(item.high),
                to_float(item.low),
                to_float(item.close),
                to_float(item.volume),
                to_float(item.amount),
                to_float(item.turnover_rate),
                2,
            )
        )
    return rows


def new_client(token: str):
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = "https://tuaremax.top"
    return pro


def sync_one(stock_code: str, token: str, write: bool) -> dict:
    for attempt in range(1, 4):
        try:
            frame = fetch_daily(new_client(token), stock_code)
            if frame.empty:
                return {"stock_code": stock_code, "source": 0, "existing": 0, "missing": 0}
            dates = existing_dates(stock_code)
            missing = missing_rows(frame, stock_code, dates)
            if write and missing:
                execute_many(
                    "INSERT IGNORE INTO trade_stock_daily "
                    "(stock_code, trade_date, open_price, high_price, low_price, close_price, "
                    "volume, amount, turnover_rate, adjustflag) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    missing,
                )
            return {
                "stock_code": stock_code,
                "source": len(frame),
                "existing": len(dates),
                "missing": len(missing),
            }
        except Exception as exc:
            if attempt == 3:
                return {"stock_code": stock_code, "error": str(exc)}
            time.sleep(attempt * 2)
    raise AssertionError("unreachable")


def main() -> int:
    if ts is None:
        print("未安装 tushare，请先安装后再运行")
        return 1
    token = load_token()
    if not token:
        print("未设置 TUSHARE_TOKEN")
        return 1

    stocks, source = stock_codes()
    if not stocks:
        print("trade_stock_status 中没有可同步的股票，请先初始化股票基础数据")
        return 1
    write = os.getenv("KLINE_SYNC_WRITE", "1") != "0"
    print(f"同步范围: {START_DATE}-{END_DATE}, 股票数: {len(stocks)}, 来源: {source}, " f"并发数: {min(MAX_WORKERS, len(stocks))}, 写入: {write}")

    results = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(stocks))) as pool:
        futures = {pool.submit(sync_one, code, token, write): code for code in stocks}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if "error" in result:
                print(f"{result['stock_code']}: ERROR {result['error']}")
            else:
                print(
                    f"{result['stock_code']}: source={result['source']}, "
                    f"existing={result['existing']}, missing={result['missing']}"
                )

    errors = [result for result in results if "error" in result]
    missing = sum(result.get("missing", 0) for result in results)
    print(f"完成: 成功 {len(results) - len(errors)}, 失败 {len(errors)}, 待补齐/已补齐 {missing}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
