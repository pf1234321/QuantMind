# -*- coding: utf-8 -*-
"""使用 Tushare 多线程补齐股票缺失日线。

运行前设置 TUSHARE_TOKEN。默认从 trade_stock_status 读取全部股票，检查并写入
TUSHARE_START_DATE 至今天的缺失行情；已有数据不会覆盖。

    TUSHARE_TOKEN=your_token python -m unittest tests.test_kline_sync -v

设置 KLINE_SYNC_WRITE=0 可仅检查、不写入数据库。

可选环境变量：
- KLINE_MAX_WORKERS：并发线程数，默认 4
- KLINE_STOCK_CODES：逗号分隔的股票代码，仅处理指定股票，例如 000001,600000
- TUSHARE_START_DATE：开始日期，默认 20220101
"""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.database import execute_many, execute_query

try:
    import tushare as ts
except ImportError:  # pragma: no cover - 环境未安装 Tushare 时由测试跳过
    ts = None


TUSHARE_START_DATE = os.getenv("TUSHARE_START_DATE", "20220101")
MAX_WORKERS = max(1, int(os.getenv("KLINE_MAX_WORKERS", "4")))


def _load_dotenv_token() -> str:
    # 严格从环境变量 / .env 读取，禁止在源码中硬编码真实 token
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


def _stock_codes() -> list[str]:
    configured = os.getenv("KLINE_STOCK_CODES", "").strip()
    if configured:
        return sorted({code.strip().upper() for code in configured.split(",") if code.strip()})

    rows = execute_query(
        "SELECT DISTINCT stock_code FROM trade_stock_status "
        "WHERE stock_code IS NOT NULL AND stock_code <> '' ORDER BY stock_code"
    )
    return [str(row["stock_code"]).strip().upper() for row in rows if row.get("stock_code")]


def _tushare_code(stock_code: str) -> str:
    code = stock_code.strip().upper()
    if "." in code:
        return code
    if code.startswith(("6", "68", "69")):
        return f"{code}.SH"
    if code.startswith(("8", "4")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _trade_dates(stock_code: str, start_date: str, end_date: str) -> set[str]:
    rows = execute_query(
        "SELECT trade_date FROM trade_stock_daily "
        "WHERE stock_code=%s AND trade_date BETWEEN %s AND %s",
        (stock_code.split(".")[0], start_date, end_date),
    )
    return {str(row["trade_date"])[:10].replace("-", "") for row in rows}


def _to_float(value):
    return None if pd.isna(value) else float(value)


def _fetch_tushare_daily(pro, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    ts_code = _tushare_code(stock_code)
    daily = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if daily is None or daily.empty:
        return pd.DataFrame()
    daily = daily.copy()
    daily["trade_date"] = daily["trade_date"].astype(str)
    daily = daily.sort_values("trade_date")

    # daily 是不复权行情；用 adj_factor 转为前复权，保持表内 adjustflag=2 的口径。
    factors = pro.adj_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if factors is None or factors.empty:
        raise RuntimeError("Tushare 未返回 adj_factor，无法安全写入前复权行情")
    factors = factors[["trade_date", "adj_factor"]].copy()
    factors["trade_date"] = factors["trade_date"].astype(str)
    daily = daily.merge(factors, on="trade_date", how="inner", validate="one_to_one")
    if daily.empty:
        raise RuntimeError("daily 与 adj_factor 没有可匹配的交易日")

    factor = daily["adj_factor"].astype(float)
    latest_factor = factor.iloc[-1]
    for column in ["open", "high", "low", "close"]:
        daily[column] = daily[column].astype(float) * factor / latest_factor
    daily["volume"] = daily["vol"].astype(float) * 100
    daily["amount"] = daily["amount"].astype(float) * 1000

    basics = pro.daily_basic(
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
        fields="ts_code,trade_date,turnover_rate",
    )
    if basics is None or basics.empty or "turnover_rate" not in basics:
        raise RuntimeError("Tushare daily_basic 未返回 turnover_rate，无法安全写入")
    basics = basics[["trade_date", "turnover_rate"]].copy()
    basics["trade_date"] = basics["trade_date"].astype(str)
    daily = daily.merge(basics, on="trade_date", how="left", validate="one_to_one")
    if daily["turnover_rate"].isna().any():
        raise RuntimeError("daily_basic 的 turnover_rate 与日 K 交易日未完全匹配")
    return daily


def _missing_rows(frame: pd.DataFrame, stock_code: str, existing_dates: set[str]) -> list[tuple]:
    db_code = stock_code.split(".")[0]
    rows = []
    for item in frame.itertuples(index=False):
        trade_date = str(item.trade_date)
        if trade_date in existing_dates:
            continue
        rows.append(
            (
                db_code,
                datetime.strptime(trade_date, "%Y%m%d").date(),
                _to_float(item.open),
                _to_float(item.high),
                _to_float(item.low),
                _to_float(item.close),
                _to_float(item.volume),
                _to_float(item.amount),
                _to_float(item.turnover_rate),
                2,
            )
        )
    return rows


def _new_tushare_client(token: str):
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = "https://tuaremax.top"
    return pro


def _sync_one(stock_code: str, token: str, start_date: str, end_date: str, write: bool) -> dict:
    try:
        pro = _new_tushare_client(token)
        frame = _fetch_tushare_daily(pro, stock_code, start_date, end_date)
        if frame.empty:
            return {"stock_code": stock_code, "tushare": 0, "existing": 0, "missing": 0}

        existing_dates = _trade_dates(stock_code, start_date, end_date)
        missing = _missing_rows(frame, stock_code, existing_dates)
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
            "tushare": len(frame),
            "existing": len(existing_dates),
            "missing": len(missing),
        }
    except Exception as exc:  # 每只股票隔离错误，其他线程继续执行
        return {"stock_code": stock_code, "error": str(exc)}


class TushareKlineSyncTest(unittest.TestCase):
    @unittest.skipUnless(ts is not None and _load_dotenv_token(), "需要 Tushare 和 TUSHARE_TOKEN")
    def test_fill_missing_kline_for_all_stocks(self):
        token = _load_dotenv_token()
        stocks = _stock_codes()
        self.assertTrue(stocks, "trade_stock_status 中没有可同步的股票")
        end_date = date.today().strftime("%Y%m%d")
        write = os.getenv("KLINE_SYNC_WRITE", "1") != "0"
        results = []

        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(stocks))) as pool:
            futures = {
                pool.submit(_sync_one, stock, token, TUSHARE_START_DATE, end_date, write): stock
                for stock in stocks
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                if "error" in result:
                    print(f"{result['stock_code']}: ERROR {result['error']}")
                else:
                    print(
                        f"{result['stock_code']}: Tushare={result['tushare']}, "
                        f"existing={result['existing']}, missing={result['missing']}"
                    )

        errors = [result for result in results if "error" in result]
        self.assertFalse(errors, f"部分股票同步失败: {errors}")


if __name__ == "__main__":
    unittest.main()
