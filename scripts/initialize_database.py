# -*- coding: utf-8 -*-
"""QuantMind 数据库一键初始化。

用法：python scripts/initialize_database.py [--skip-kline]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from scripts.init_db import init_db


def _connect(database: str | None = None):
    kwargs = {"host": settings.DB_HOST, "port": settings.DB_PORT, "user": settings.DB_USER,
              "password": settings.DB_PASSWORD, "charset": "utf8mb4", "autocommit": False}
    if database:
        kwargs["database"] = database
    return pymysql.connect(**kwargs)


def ensure_database() -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{settings.DB_NAME}` DEFAULT CHARACTER SET utf8mb4")
        conn.commit()
    finally:
        conn.close()


def _comment_for_column(name: str, current: str | None) -> str:
    if current:
        return current
    known = {"id": "自增主键", "stock_code": "股票代码", "stock_name": "股票简称", "trade_date": "交易日期",
             "created_at": "创建时间", "updated_at": "更新时间", "open_price": "开盘价", "high_price": "最高价",
             "low_price": "最低价", "close_price": "收盘价", "volume": "成交量", "amount": "成交额",
             "list_date": "上市日期", "sector_1": "申万一级行业", "sector_2": "申万二级行业", "sector_3": "申万三级行业",
             "total_shares": "总股本(股)", "float_shares": "流通股本(股)"}
    return known.get(name, f"字段：{name}")


def _sql_default(value: object) -> str:
    if value is None:
        return "DEFAULT NULL"
    text = str(value)
    if text.upper().startswith("CURRENT_TIMESTAMP"):
        return f"DEFAULT {text}"
    return "DEFAULT '" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def ensure_chinese_comments() -> tuple[int, int]:
    conn = _connect(settings.DB_NAME)
    tables = columns = 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE'", (settings.DB_NAME,))
            for (table,) in cur.fetchall():
                cur.execute(f"ALTER TABLE `{table}` COMMENT=%s", (f"QuantMind业务表：{table}",))
                tables += 1
                cur.execute("SELECT column_name,column_type,is_nullable,column_default,extra,column_comment FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", (settings.DB_NAME, table))
                for name, column_type, nullable, default, extra, comment in cur.fetchall():
                    if comment:
                        continue
                    null_sql = "NULL" if nullable == "YES" else "NOT NULL"
                    extra_sql = " AUTO_INCREMENT" if "auto_increment" in (extra or "").lower() else ""
                    update_sql = " ON UPDATE CURRENT_TIMESTAMP" if "on update" in (extra or "").lower() else ""
                    cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{name}` {column_type} {null_sql} {_sql_default(default)}{extra_sql}{update_sql} COMMENT %s", (_comment_for_column(name, comment),))
                    columns += 1
        conn.commit()
    finally:
        conn.close()
    return tables, columns


def import_stock_status() -> int:
    path = ROOT / "data" / "a股全量_基础_申万2021_唯一行业.csv"
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = (row.get("symbol") or "").strip()
            if not code:
                continue
            list_date = (row.get("list_date") or "").strip() or None
            if list_date and len(list_date) == 8:
                list_date = f"{list_date[:4]}-{list_date[4:6]}-{list_date[6:]}"
            rows.append((code, (row.get("name") or "").strip() or None, list_date,
                         (row.get("申万一级行业") or "").strip() or None, (row.get("申万二级行业") or "").strip() or None,
                         (row.get("申万三级行业") or "").strip() or None))
    conn = _connect(settings.DB_NAME)
    try:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO trade_stock_status (stock_code,stock_name,list_date,sector_1,sector_2,sector_3) VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE stock_name=VALUES(stock_name),list_date=VALUES(list_date),sector_1=VALUES(sector_1),sector_2=VALUES(sector_2),sector_3=VALUES(sector_3)", rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-kline", action="store_true")
    args = parser.parse_args()
    ensure_database()
    init_db()
    table_count, column_count = ensure_chinese_comments()
    stock_count = import_stock_status()
    kline_result = {"skipped": True}
    if not args.skip_kline:
        from app.services.kline_sync import sync_kline
        kline_result = sync_kline(force_refresh=True)
    print({"tables_commented": table_count, "columns_commented": column_count, "stocks_imported": stock_count, "kline": kline_result})


if __name__ == "__main__":
    main()
