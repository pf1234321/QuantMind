# -*- coding: utf-8 -*-
"""板块每日聚合 + 等权合成指数（写入 trade_sector_daily）
迁移自: 11周 sector_index_builder.py（核心逻辑保留：累乘合成指数，仅支持一二级板块）
"""
import logging
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from app.database import execute_many, execute_query
from app.services.industry_sync import get_sector_member_codes, list_sectors_from_db

logger = logging.getLogger(__name__)

BASE_INDEX = 1000.0

_stock_name_cache: dict[str, str] = {}


def get_stock_name(code: str) -> str:
    if code in _stock_name_cache:
        return _stock_name_cache[code]
    rows = execute_query(
        "SELECT stock_name FROM trade_stock_status WHERE stock_code = %s", (code,)
    )
    name = rows[0]["stock_name"] if rows and rows[0].get("stock_name") else code
    _stock_name_cache[code] = name
    return name


def get_all_trade_dates() -> list[date]:
    rows = execute_query(
        "SELECT DISTINCT trade_date FROM trade_stock_daily ORDER BY trade_date ASC"
    )
    return [r["trade_date"] for r in rows]


def get_prev_close_idx(sector_name: str, sector_level: int, prev_trade_date: date) -> float:
    rows = execute_query(
        "SELECT close_idx FROM trade_sector_daily "
        "WHERE sector_name=%s AND sector_level=%s AND trade_date=%s",
        (sector_name, sector_level, prev_trade_date),
    )
    if rows and rows[0]["close_idx"] is not None:
        return float(rows[0]["close_idx"])
    return BASE_INDEX


def fetch_member_kline_panel(member_codes: list[str], trade_dates: list[date]) -> dict:
    if not member_codes or not trade_dates:
        return {}
    ph_codes = ",".join(["%s"] * len(member_codes))
    ph_dates = ",".join(["%s"] * len(trade_dates))
    sql = f"""
        SELECT stock_code, trade_date, open_price, high_price, low_price,
               close_price, volume, amount, turnover_rate
        FROM trade_stock_daily
        WHERE stock_code IN ({ph_codes}) AND trade_date IN ({ph_dates})
    """
    params = list(member_codes) + list(trade_dates)
    rows = execute_query(sql, params)
    result = {}
    for r in rows:
        result[(r["stock_code"], r["trade_date"])] = {
            "open": float(r["open_price"]) if r["open_price"] is not None else None,
            "high": float(r["high_price"]) if r["high_price"] is not None else None,
            "low": float(r["low_price"]) if r["low_price"] is not None else None,
            "close": float(r["close_price"]) if r["close_price"] is not None else None,
            "volume": int(r["volume"]) if r["volume"] is not None else 0,
            "amount": float(r["amount"]) if r["amount"] is not None else 0.0,
            "turnover": float(r["turnover_rate"]) if r["turnover_rate"] is not None else 0.0,
        }
    return result


def aggregate_sector_one_day(sector_name, sector_level, member_codes, trade_date,
                             prev_trade_date, prev_close_idx, kline_panel):
    pcts = []
    for code in member_codes:
        today = kline_panel.get((code, trade_date))
        if not today or today["close"] is None:
            continue
        prev = kline_panel.get((code, prev_trade_date)) if prev_trade_date else None
        pcts.append((code, today, prev))

    if not pcts:
        return None

    rise = fall = flat = lu = ld = 0
    pct_list = []
    for code, today, prev in pcts:
        if not prev or not prev["close"]:
            continue
        pct = today["close"] / prev["close"] - 1
        pct_list.append((code, pct))
        if pct > 0.0001:
            rise += 1
        elif pct < -0.0001:
            fall += 1
        else:
            flat += 1
        if pct >= 0.097:
            lu += 1
        elif pct <= -0.097:
            ld += 1

    change_pct = float(np.mean([p for _, p in pct_list])) * 100 if pct_list else 0.0

    if pct_list:
        top_code, top_pct = max(pct_list, key=lambda x: x[1])
    else:
        top_code, top_pct = "", 0.0

    total_volume = sum(t["volume"] for _, t, _ in pcts)
    total_amount = sum(t["amount"] for _, t, _ in pcts)

    open_rets, high_rets, low_rets, close_rets = [], [], [], []
    for code, today, prev in pcts:
        if not prev or not prev["close"]:
            continue
        if today["open"] is not None:
            open_rets.append(today["open"] / prev["close"] - 1)
        if today["high"] is not None:
            high_rets.append(today["high"] / prev["close"] - 1)
        if today["low"] is not None:
            low_rets.append(today["low"] / prev["close"] - 1)
        close_rets.append(today["close"] / prev["close"] - 1)

    if close_rets:
        open_idx = prev_close_idx * (1 + np.mean(open_rets)) if open_rets else prev_close_idx
        high_idx = prev_close_idx * (1 + np.mean(high_rets)) if high_rets else prev_close_idx
        low_idx = prev_close_idx * (1 + np.mean(low_rets)) if low_rets else prev_close_idx
        close_idx = prev_close_idx * (1 + np.mean(close_rets))
    else:
        open_idx = high_idx = low_idx = close_idx = prev_close_idx

    turnover_list = [t["turnover"] for _, t, _ in pcts]
    avg_turnover = float(np.mean(turnover_list)) if turnover_list else 0.0

    return {
        "sector_name": sector_name, "sector_level": sector_level,
        "trade_date": trade_date, "change_pct": round(change_pct, 4),
        "stock_count": len(member_codes),
        "rise_count": rise, "fall_count": fall, "flat_count": flat,
        "limit_up": lu, "limit_down": ld,
        "top_stock": top_code, "top_stock_name": get_stock_name(top_code) if top_code else "",
        "top_stock_pct": round(top_pct * 100, 2),
        "open_idx": round(open_idx, 4), "high_idx": round(high_idx, 4),
        "low_idx": round(low_idx, 4), "close_idx": round(close_idx, 4),
        "total_volume": total_volume, "total_amount": round(total_amount, 2),
        "avg_turnover": round(avg_turnover, 4), "kline_stock_count": len(pcts),
    }


SAVE_SQL = """
INSERT INTO trade_sector_daily
    (sector_name, sector_level, trade_date, change_pct, stock_count,
     rise_count, fall_count, flat_count, limit_up, limit_down,
     top_stock, top_stock_name, top_stock_pct,
     open_idx, high_idx, low_idx, close_idx,
     total_volume, total_amount, avg_turnover, kline_stock_count)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON DUPLICATE KEY UPDATE
    change_pct=VALUES(change_pct), stock_count=VALUES(stock_count),
    rise_count=VALUES(rise_count), fall_count=VALUES(fall_count),
    flat_count=VALUES(flat_count), limit_up=VALUES(limit_up),
    limit_down=VALUES(limit_down), top_stock=VALUES(top_stock),
    top_stock_name=VALUES(top_stock_name), top_stock_pct=VALUES(top_stock_pct),
    open_idx=VALUES(open_idx), high_idx=VALUES(high_idx),
    low_idx=VALUES(low_idx), close_idx=VALUES(close_idx),
    total_volume=VALUES(total_volume), total_amount=VALUES(total_amount),
    avg_turnover=VALUES(avg_turnover), kline_stock_count=VALUES(kline_stock_count)
"""


def save_sector_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    rows_tuples = [(
        r["sector_name"], r["sector_level"], r["trade_date"], r["change_pct"], r["stock_count"],
        r["rise_count"], r["fall_count"], r["flat_count"], r["limit_up"], r["limit_down"],
        r["top_stock"], r["top_stock_name"], r["top_stock_pct"],
        r["open_idx"], r["high_idx"], r["low_idx"], r["close_idx"],
        r["total_volume"], r["total_amount"], r["avg_turnover"], r["kline_stock_count"],
    ) for r in rows]
    return execute_many(SAVE_SQL, rows_tuples)


def rebuild_one_sector(sector_name: str, sector_level: int, target_dates: list[date], all_dates: list[date]) -> int:
    members = get_sector_member_codes(sector_name, level=sector_level)
    if not members:
        return 0

    date_to_idx = {d: i for i, d in enumerate(all_dates)}
    fetch_dates = set()
    for d in target_dates:
        fetch_dates.add(d)
        idx = date_to_idx.get(d)
        if idx is not None and idx > 0:
            fetch_dates.add(all_dates[idx - 1])
    panel = fetch_member_kline_panel(members, sorted(fetch_dates))

    rows = []
    prev_close_idx = None
    for d in target_dates:
        idx = date_to_idx.get(d)
        prev_d = all_dates[idx - 1] if idx and idx > 0 else None
        if prev_close_idx is None:
            prev_close_idx = get_prev_close_idx(sector_name, sector_level, prev_d) if prev_d else BASE_INDEX
        row = aggregate_sector_one_day(
            sector_name=sector_name, sector_level=sector_level,
            member_codes=members, trade_date=d, prev_trade_date=prev_d,
            prev_close_idx=prev_close_idx, kline_panel=panel,
        )
        if row is None:
            continue
        rows.append(row)
        prev_close_idx = row["close_idx"]

    return save_sector_rows(rows)


def rebuild_all_sectors(level: int = 2, days: Optional[int] = None, full: bool = False) -> dict:
    """重算所有板块的 trade_sector_daily。level: 1/2，full=True 全量回填"""
    all_dates = get_all_trade_dates()
    if not all_dates:
        return {"written": 0, "error": "trade_stock_daily 无数据，请先同步 K 线"}

    if full:
        target_dates = all_dates
    else:
        n = days or 30
        target_dates = all_dates[-n:]

    sectors = list_sectors_from_db(level=level)
    total = 0
    for sector in sectors:
        total += rebuild_one_sector(sector, level, target_dates, all_dates)

    logger.info("[板块] level=%s 合成完成, 写入 %d 行", level, total)
    return {
        "level": level, "sectors": len(sectors), "written": total,
        "range": [str(target_dates[0]), str(target_dates[-1])],
        "kline_range": [str(all_dates[0]), str(all_dates[-1])],
        "kline_latest_is_today": all_dates[-1] >= date.today(),
        "warning": None if all_dates[-1] >= date.today() else "K线未覆盖今天，板块无法生成今天数据",
    }
