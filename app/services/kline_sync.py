# -*- coding: utf-8 -*-
"""K线数据同步：BaoStock A股日线数据，统一使用前复权。"""
import logging
import threading
import time
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from app.config import settings
from app.database import execute_many, execute_query

logger = logging.getLogger(__name__)

KLINE_RETRY_DELAYS = (2, 5)
_BAOSTOCK_LOCK = threading.Lock()

INSERT_SQL = """
INSERT INTO trade_stock_daily
(stock_code, trade_date, open_price, high_price, low_price, close_price,
 volume, amount, turnover_rate, adjustflag)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 2)
ON DUPLICATE KEY UPDATE
open_price=VALUES(open_price), high_price=VALUES(high_price),
low_price=VALUES(low_price), close_price=VALUES(close_price),
volume=VALUES(volume), amount=VALUES(amount),
turnover_rate=VALUES(turnover_rate), adjustflag=VALUES(adjustflag)
"""


def _date_arg(value: str) -> str:
    return value.replace("-", "")[:8]


def _stock_symbol(code: str) -> str:
    """转换为数据库和 BaoStock 使用的六位纯数字代码。"""
    raw_code = (code or "").strip().upper().split(".", 1)[0]
    if raw_code.startswith("T") and raw_code[1:].isdigit():
        raw_code = raw_code[1:]
    if not raw_code.isdigit() or len(raw_code) > 6:
        raise ValueError(f"股票代码格式无效: {code}")
    return raw_code.zfill(6)


def _float(value, default=0.0):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _baostock_date(value: str) -> str:
    normalized = _date_arg(value)
    return f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:8]}"


def _baostock_code(code: str) -> str:
    symbol = _stock_symbol(code)
    normalized = (code or "").strip().upper()
    if normalized.endswith((".SH", ".SZ")):
        market = normalized.rsplit(".", 1)[1].lower()
    else:
        market = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
    return f"{market}.{symbol}"


def _query_baostock(symbol: str, start_date: str, end_date: str):
    """使用已登录的 BaoStock 会话获取前复权日线。"""
    import baostock as bs

    result = bs.query_history_k_data_plus(
        code=_baostock_code(symbol),
        fields="date,open,high,low,close,volume,amount,turn",
        start_date=_baostock_date(start_date),
        end_date=_baostock_date(end_date),
        frequency="d",
        adjustflag="2",
    )
    if result is None:
        raise ConnectionError("BaoStock 查询未返回结果")
    if result.error_code != "0":
        raise ConnectionError(f"BaoStock 查询失败: {result.error_msg}")
    rows = []
    while result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=[
        "日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "换手率",
    ])


def _parse_rows(df, code_num: str) -> list[tuple]:
    if df is None or df.empty:
        return []
    required = {"日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"BaoStock K线字段缺失: {sorted(missing)}")
    rows = []
    for item in df.to_dict("records"):
        trade_date = item.get("日期")
        if trade_date is None or trade_date == "nan":
            continue
        rows.append((
            code_num,
            str(trade_date).replace("-", "")[:8],
            _float(item.get("开盘")),
            _float(item.get("最高")),
            _float(item.get("最低")),
            _float(item.get("收盘")),
            int(_float(item.get("成交量"))),
            _float(item.get("成交额")),
            _float(item.get("换手率"), default=None) if "换手率" in item else None,
        ))
    return rows


def sync_kline_baostock(stock_codes: Optional[list] = None, start_date: Optional[str] = None,
                        end_date: Optional[str] = None, adjustflag: str = "2",
                        force_refresh: bool = False) -> dict:
    """同步 BaoStock qfq 前复权日线，保留旧入口名称兼容现有调用方。"""
    if adjustflag != "2":
        raise ValueError("QuantMind K线统一使用前复权，adjustflag 必须为 2")
    if stock_codes is None:
        stock_codes = [r["stock_code"] for r in execute_query(
            "SELECT DISTINCT stock_code FROM trade_stock_status"
        )]

    total_written = 0
    failed_stocks = []
    import baostock as bs

    with _BAOSTOCK_LOCK:
        login = bs.login()
        if login.error_code != "0":
            raise ConnectionError(f"BaoStock 登录失败: {login.error_msg}")
        try:
            for code in stock_codes:
                try:
                    code_num = _stock_symbol(code)
                except ValueError as exc:
                    failed_stocks.append({"stock_code": str(code), "attempts": 0, "error": str(exc), "type": type(exc).__name__})
                    logger.warning("跳过无效股票代码: %s", code)
                    continue
                code_start = start_date
                if code_start is None and force_refresh:
                    code_start = settings.KLINE_DATA_START
                if code_start is None:
                    latest = execute_query(
                        "SELECT MAX(trade_date) AS latest FROM trade_stock_daily WHERE stock_code=%s",
                        (code_num,),
                    )
                    latest_date = latest[0]["latest"] if latest and latest[0]["latest"] else None
                    code_start = (latest_date + timedelta(days=1)).strftime("%Y%m%d") if latest_date else settings.KLINE_DATA_START
                code_end = end_date or date.today().strftime("%Y%m%d")
                if _date_arg(code_start) > _date_arg(code_end):
                    continue

                rows = None
                last_error = None
                attempts = 0
                for attempt in range(settings.KLINE_MAX_ATTEMPTS):
                    attempts = attempt + 1
                    try:
                        rows = _parse_rows(_query_baostock(code, code_start, code_end), code_num)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_error = {"error": str(exc), "type": type(exc).__name__}
                        error_text = f"{type(exc).__name__}: {exc}".lower()
                        retryable = isinstance(exc, (ConnectionError, TimeoutError, UnicodeDecodeError)) or any(
                            marker in error_text
                            for marker in ("connection", "remote end closed", "timed out", "timeout", "502", "503", "504")
                        )
                        if not retryable or attempts >= settings.KLINE_MAX_ATTEMPTS:
                            break
                        delay = KLINE_RETRY_DELAYS[min(attempt, len(KLINE_RETRY_DELAYS) - 1)]
                        logger.warning("BaoStock K线请求异常，%s秒后重试: %s attempt=%s error=%s", delay, code_num, attempts, exc)
                        time.sleep(delay)

                if rows is None:
                    failed_stocks.append({"stock_code": code_num, "attempts": attempts, **(last_error or {})})
                    logger.warning("BaoStock 股票同步失败: %s, %s", code_num, last_error)
                    continue
                try:
                    if rows:
                        execute_many(INSERT_SQL, rows)
                        total_written += len(rows)
                except Exception as exc:  # noqa: BLE001
                    failed_stocks.append({"stock_code": code_num, "attempts": 1, "error": str(exc), "type": type(exc).__name__})
                    logger.exception("K线写库失败: %s", code_num)
        finally:
            bs.logout()

    return {
        "source": "baostock",
        "adjust": "qfq",
        "written": total_written,
        "failed": len(failed_stocks),
        "total": len(stock_codes),
        "failed_stocks": failed_stocks,
    }


def sync_kline(stock_codes: Optional[list] = None, start_date: Optional[str] = None,
               end_date: Optional[str] = None, adjustflag: str = "2",
               force_refresh: bool = False) -> dict:
    """同步 BaoStock 日线数据；默认增量同步，force_refresh=True 时重写历史区间。"""
    return sync_kline_baostock(stock_codes=stock_codes, start_date=start_date,
                               end_date=end_date, adjustflag=adjustflag,
                               force_refresh=force_refresh)
