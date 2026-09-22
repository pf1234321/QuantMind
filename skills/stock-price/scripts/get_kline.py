#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K 线数据获取脚本（本地 MySQL）
从 wucai_trade.trade_stock_daily 表读取股票日线数据，输出 JSON
"""

import sys
import json
import pymysql

# ========== 数据库配置 ==========
DB_CONFIG = {
    "host": "localhost",
    "port": 3309,
    "user": "root",
    "password": "root",
    "database": "wucai_trade",
    "charset": "utf8mb4",
}

# 表字段映射：输出字段 → 数据库字段
COLUMN_MAP = {
    "date": "trade_date",
    "open": "open_price",
    "high": "high_price",
    "low": "low_price",
    "close": "close_price",
    "volume": "volume",
    "amount": "amount",
}


def get_connection():
    return pymysql.connect(**DB_CONFIG)


def strip_exchange_suffix(stock_code):
    """去掉交易所后缀：'000001.SZ' → '000001'"""
    return stock_code.split(".")[0]


def get_kline_data(stock_code, period='1d', start_date='', end_date='', count=100):
    """
    从本地数据库获取 K 线数据

    Args:
        stock_code: 股票代码，如 '000001' 或 '000001.SZ'
        period: 周期（仅支持 '1d' 日线）
        start_date: 开始日期 'YYYY-MM-DD'
        end_date:   结束日期 'YYYY-MM-DD'
        count:      返回最近 N 条
    """
    if period != '1d':
        return {"error": f"本地数据库仅支持日线 (1d)，不支持 {period}"}

    stock_code = strip_exchange_suffix(stock_code)

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # 构建查询
        where_parts = ["stock_code = %s"]
        params = [stock_code]

        if start_date:
            where_parts.append("trade_date >= %s")
            params.append(start_date)
        if end_date:
            where_parts.append("trade_date <= %s")
            params.append(end_date)

        where_clause = " AND ".join(where_parts)
        sql = f"""
            SELECT trade_date, open_price, high_price, low_price,
                   close_price, volume, amount
            FROM trade_stock_daily
            WHERE {where_clause}
            ORDER BY trade_date DESC
            LIMIT %s
        """
        params.append(count)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        if not rows:
            return {"error": f"未查询到 {stock_code} 的数据"}

        records = []
        for row in reversed(rows):  # 正序返回
            records.append({
                "date": str(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": int(row[5]),
                "amount": float(row[6]),
            })

        cursor.close()
        conn.close()

        return {
            "stock_code": stock_code,
            "period": period,
            "data_count": len(records),
            "data": records,
        }

    except pymysql.Error as e:
        return {"error": f"数据库错误: {str(e)}"}
    except Exception as e:
        return {"error": f"获取失败: {str(e)}"}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "用法: get_kline.py <股票代码> [周期] [条数]"}, ensure_ascii=False))
        sys.exit(1)

    stock_code = sys.argv[1]
    period = sys.argv[2] if len(sys.argv) > 2 else '1d'
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 100

    result = get_kline_data(stock_code, period=period, count=count)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
