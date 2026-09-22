# -*- coding: utf-8 -*-
"""研报数据同步（akshare：机构评级和盈利预测）。"""
import logging
import time

import akshare as ak

from app.database import execute_many, execute_update, table_exists

logger = logging.getLogger(__name__)

INSERT_SQL = """
INSERT INTO trade_report_consensus
(stock_code, broker, report_date, rating, target_price,
 eps_forecast_current, eps_forecast_next, revenue_forecast,
 net_profit_forecast, source_file)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
rating=COALESCE(VALUES(rating), rating),
eps_forecast_current=COALESCE(VALUES(eps_forecast_current), eps_forecast_current),
eps_forecast_next=COALESCE(VALUES(eps_forecast_next), eps_forecast_next),
revenue_forecast=COALESCE(VALUES(revenue_forecast), revenue_forecast),
net_profit_forecast=COALESCE(VALUES(net_profit_forecast), net_profit_forecast),
source_file=VALUES(source_file)
"""


def _ensure_schema() -> None:
    """为现有数据库补充净利润预测字段，兼容旧 schema。"""
    if not table_exists("trade_report_consensus"):
        return
    execute_update(
        "ALTER TABLE trade_report_consensus ADD COLUMN net_profit_forecast "
        "DECIMAL(20,4) NULL COMMENT '净利润预测' AFTER revenue_forecast"
    ) if not _column_exists("net_profit_forecast") else None


def _column_exists(column: str) -> bool:
    from app.database import execute_query
    from app.config import settings
    rows = execute_query(
        "SELECT COUNT(*) AS cnt FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name='trade_report_consensus' AND column_name=%s",
        (settings.DB_NAME, column),
    )
    return bool(rows and rows[0]["cnt"])


def sync_report(stock_codes: list[tuple[str, str]], request_interval: float = 0.2,
                retries: int = 2) -> dict:
    """同步研报，区分接口失败和空数据，并按唯一键合并预测指标。"""
    _ensure_schema()
    total = failed = empty = 0
    for code_num, name in stock_codes:
        stock_written = 0
        for func, label in (
            (_sync_institute_recommend, "机构评级"),
            (_sync_profit_forecast, "盈利预测"),
        ):
            for attempt in range(retries + 1):
                try:
                    written = func(code_num)
                    stock_written += written
                    if written == 0:
                        empty += 1
                    break
                except Exception as e:
                    if "no text parsed from document" in str(e):
                        empty += 1
                        break
                    if attempt >= retries:
                        logger.exception("[研报] %s(%s) %s 失败: %s", name, code_num, label, e)
                        failed += 1
                    else:
                        time.sleep(request_interval * (attempt + 1))
            time.sleep(request_interval)
        total += stock_written
    return {
        "source": "akshare", "written": total, "failed": failed,
        "empty": empty, "stocks": len(stock_codes),
    }


def _sync_institute_recommend(code_num: str) -> int:
    df = ak.stock_institute_recommend_detail(symbol=code_num)
    if df is None or df.empty:
        return 0
    date_col = "评级日期" if "评级日期" in df.columns else "日期"
    broker_col = "评级机构" if "评级机构" in df.columns else "机构名称"
    required = {date_col, broker_col, "最新评级"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"机构评级字段缺失: {sorted(missing)}，实际字段: {list(df.columns)}")
    rows = []
    for _, r in df.iterrows():
        report_date = str(r.get(date_col, "")).replace("-", "")[:8]
        if len(report_date) != 8 or not report_date.isdigit():
            continue
        rows.append((
            code_num, str(r.get(broker_col, ""))[:50], report_date,
            str(r.get("最新评级", ""))[:20], None,
            None, None, None, None, "eastmoney",
        ))
    if rows:
        execute_many(INSERT_SQL, rows)
    return len(rows)


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sync_profit_forecast(code_num: str) -> int:
    """按股票和报告年度合并 EPS、净利润、营收预测后一次 upsert。"""
    indicators = {
        "预测年报每股收益": "eps_forecast_current",
        "预测年报净利润": "net_profit_forecast",
        "预测年报主营业务收入": "revenue_forecast",
    }
    merged = {}
    written = 0
    for indicator, field in indicators.items():
        df = ak.stock_profit_forecast_ths(symbol=code_num, indicator=indicator)
        if df is None or df.empty:
            continue
        year_col = "年度" if "年度" in df.columns else "报告期"
        value_col = "均值" if "均值" in df.columns else "预测值"
        if year_col not in df.columns or value_col not in df.columns:
            raise ValueError(f"{indicator} 字段缺失，实际字段: {list(df.columns)}")
        for _, r in df.iterrows():
            year = str(r.get(year_col, ""))[:4]
            if len(year) != 4 or not year.isdigit():
                continue
            key = f"{year}-12-31"
            merged.setdefault(key, {
                "eps_forecast_current": None,
                "net_profit_forecast": None,
                "revenue_forecast": None,
            })[field] = _to_float(r.get(value_col))
    rows = []
    for report_date, values in merged.items():
        rows.append((
            code_num, "一致预期", report_date, "买入", None,
            values["eps_forecast_current"], None,
            values["revenue_forecast"], values["net_profit_forecast"], "ths",
        ))
    if rows:
        execute_many(INSERT_SQL, rows)
        written = len(rows)
    return written
