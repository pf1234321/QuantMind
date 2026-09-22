# -*- coding: utf-8 -*-
"""宏观数据同步（akshare）
迁移自: 02周 3-宏观数据采集.py
表: trade_macro_indicator（宽表：一行一个月度指标）+ trade_rate_daily（日频利率）
"""
import logging
import re
from datetime import datetime

import akshare as ak
import pandas as pd

from app.database import execute_many

logger = logging.getLogger(__name__)

# trade_macro_indicator 宽表写入（唯一键 indicator_date）
INSERT_MACRO_SQL = """
INSERT INTO trade_macro_indicator
(indicator_date, cpi_yoy, ppi_yoy, pmi, m2_yoy, shrzgm, lpr_1y, lpr_5y, data_source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
cpi_yoy=VALUES(cpi_yoy), ppi_yoy=VALUES(ppi_yoy), pmi=VALUES(pmi),
m2_yoy=VALUES(m2_yoy), shrzgm=VALUES(shrzgm),
lpr_1y=VALUES(lpr_1y), lpr_5y=VALUES(lpr_5y)
"""

# trade_rate_daily 宽表写入（唯一键 rate_date）
INSERT_RATE_SQL = """
INSERT INTO trade_rate_daily
(rate_date, cn_bond_10y, us_bond_10y, data_source)
VALUES (%s, %s, %s, %s)
ON DUPLICATE KEY UPDATE cn_bond_10y=VALUES(cn_bond_10y), us_bond_10y=VALUES(us_bond_10y)
"""

# 月份字符串 -> 月末日期 YYYY-MM-DD
def _month_end(month_str: str) -> str:
    try:
        value = str(month_str).strip()
        if not value or value.lower() in {"nan", "nat", "none"}:
            return None
        if isinstance(month_str, (datetime, pd.Timestamp)):
            dt = month_str.to_pydatetime() if isinstance(month_str, pd.Timestamp) else month_str
        else:
            match = re.search(r"(\d{4})\D{0,3}(\d{1,2})", value)
            if not match:
                return None
            dt = datetime(int(match.group(1)), int(match.group(2)), 1)
        # 月末
        if dt.month == 12:
            return f"{dt.year}-12-31"
        next_month = datetime(dt.year, dt.month + 1, 1)
        return (next_month - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        return None


def _f(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _col(df: pd.DataFrame, *candidates: str, contains: str = None) -> str:
    """按候选名 / 包含关键字定位列（兼容 akshare 版本列名变动）"""
    for c in candidates:
        if c in df.columns:
            return c
    if contains:
        for c in df.columns:
            if contains in str(c):
                return c
    # 兜底：日期列之后的第一列
    date_idx = None
    for i, c in enumerate(df.columns):
        if any(k in str(c) for k in ("日期", "月份", "时间")):
            date_idx = i
            break
    if date_idx is not None and date_idx + 1 < len(df.columns):
        return df.columns[date_idx + 1]
    return df.columns[-1]


def _month_col(df: pd.DataFrame) -> str:
    for c in df.columns:
        if "月" in str(c) or "日期" in str(c) or "时间" in str(c):
            return c
    return df.columns[0]


def _fetch_series(func, value_columns: tuple[str, ...], contains: str = "") -> dict:
    """从 AkShare 指标表提取日期和值，兼容列名变化并过滤无效日期。"""
    df = func()
    if df is None or df.empty:
        return {}
    value_col = _col(df, *value_columns, contains=contains)
    date_col = _month_col(df)
    result = {}
    for _, row in df.iterrows():
        key = _month_end(row.get(date_col))
        if key:
            result[key] = _f(row.get(value_col))
    return result


def _fetch_cpi() -> dict:
    return _fetch_series(ak.macro_china_cpi, ("全国-同比增长", "今值"), "同比增长")


def _fetch_ppi() -> dict:
    return _fetch_series(ak.macro_china_ppi, ("当月同比增长", "今值"), "同比增长")


def _fetch_pmi() -> dict:
    return _fetch_series(ak.macro_china_pmi, ("制造业-指数", "今值"), "制造业")


def _fetch_m2() -> dict:
    return _fetch_series(
        ak.macro_china_supply_of_money,
        ("货币和准货币（广义货币M2）同比增长", "今值"),
        "M2",
    )


def _fetch_shrzgm() -> dict:
    return _fetch_series(ak.macro_china_shrzgm, ("社会融资规模增量", "今值"), "社会融资")


def _fetch_lpr() -> dict:
    df = ak.macro_china_lpr()
    if df is None or df.empty:
        return {}
    date_col = _col(df, "TRADE_DATE", "日期", "月份")
    one_col = _col(df, "LPR1Y", "1年期LPR", contains="LPR1Y")
    five_col = _col(df, "LPR5Y", "5年期LPR", contains="LPR5Y")
    result = {}
    for _, row in df.iterrows():
        key = _month_end(row.get(date_col))
        if key:
            result[key] = (_f(row.get(one_col)), _f(row.get(five_col)))
    return result


def sync_macro() -> dict:
    """同步全部宏观指标到宽表 trade_macro_indicator"""
    cpi = _fetch_cpi()
    ppi = _fetch_ppi()
    pmi = _fetch_pmi()
    m2 = _fetch_m2()
    shrzgm = _fetch_shrzgm()
    lpr = _fetch_lpr()

    all_dates = {d for d in (set(cpi) | set(ppi) | set(pmi) | set(m2) | set(shrzgm) | set(lpr)) if d}
    rows = []
    for d in sorted(all_dates):
        lpr_1y, lpr_5y = lpr.get(d, (None, None))
        rows.append((
            d, cpi.get(d), ppi.get(d), pmi.get(d),
            m2.get(d), shrzgm.get(d), lpr_1y, lpr_5y, "akshare",
        ))
    written = 0
    if rows:
        execute_many(INSERT_MACRO_SQL, rows)
        written = len(rows)
    logger.info("[宏观] trade_macro_indicator 入库 %d 行", written)

    rate_written = sync_rate()
    return {"macro_written": written, "rate_written": rate_written}


def sync_rate() -> int:
    """中美国债收益率（日频）写入 trade_rate_daily 宽表"""
    df = ak.bond_zh_us_rate(start_date="19900101")
    rows = []
    date_col = _month_col(df)
    cn_col = _col(df, "中国国债收益率10年", "中债国债到期收益率:10年", contains="中国国债收益率10年")
    us_col = _col(df, "美国国债收益率10年", contains="美国国债收益率10年")
    for _, r in df.iterrows():
        d = str(r[date_col]).replace("-", "")
        if len(d) != 8:
            continue
        d_fmt = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        cn10 = _f(r.get(cn_col))
        us10 = _f(r.get(us_col))
        rows.append((d_fmt, cn10, us10, "akshare"))
    written = 0
    if rows:
        execute_many(INSERT_RATE_SQL, rows)
        written = len(rows)
    logger.info("[宏观] trade_rate_daily 入库 %d 行", written)
    return written
