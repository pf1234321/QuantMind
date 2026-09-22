# -*- coding: utf-8 -*-
"""基于板块强度和成分股动量的板块选股机会。"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from app.database import execute_many, execute_query, execute_update
from app.services.industry_sync import get_sector_member_codes, list_sectors_from_db

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trade_sector_opportunity (
  id BIGINT NOT NULL AUTO_INCREMENT,
  sector_name VARCHAR(50) NOT NULL,
  sector_level TINYINT NOT NULL,
  trade_date DATE NOT NULL,
  phase VARCHAR(30) NOT NULL,
  phase_desc VARCHAR(100) NOT NULL,
  strength_score DECIMAL(12,6) NOT NULL,
  sector_rank INT NOT NULL,
  mom_21 DECIMAL(12,6) NOT NULL,
  rs_60 DECIMAL(12,6) NOT NULL,
  vol_ratio DECIMAL(12,6) NOT NULL,
  rise_count INT DEFAULT 0,
  fall_count INT DEFAULT 0,
  total_amount DECIMAL(22,2) DEFAULT 0,
  top_stock VARCHAR(20) DEFAULT NULL,
  top_stock_name VARCHAR(50) DEFAULT NULL,
  confirmation_status VARCHAR(30) NOT NULL,
  confirmation_days INT NOT NULL DEFAULT 1,
  reason TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sector_opportunity (sector_name, sector_level, trade_date, phase),
  KEY idx_sector_opportunity_date (trade_date),
  KEY idx_sector_opportunity_phase (phase, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='板块选股机会';

CREATE TABLE IF NOT EXISTS trade_sector_opportunity_stock (
  id BIGINT NOT NULL AUTO_INCREMENT,
  opportunity_id BIGINT NOT NULL,
  sector_name VARCHAR(50) NOT NULL,
  sector_level TINYINT NOT NULL,
  trade_date DATE NOT NULL,
  stock_code VARCHAR(20) NOT NULL,
  stock_name VARCHAR(50) DEFAULT NULL,
  stock_rank INT NOT NULL,
  stock_score DECIMAL(12,6) NOT NULL,
  roc_5 DECIMAL(12,6) NOT NULL,
  roc_20 DECIMAL(12,6) NOT NULL,
  roc_60 DECIMAL(12,6) NOT NULL,
  vol_ratio DECIMAL(12,6) NOT NULL,
  trend_direction VARCHAR(20) NOT NULL,
  ma_status VARCHAR(30) NOT NULL,
  close_price DECIMAL(10,2) NOT NULL,
  volume BIGINT DEFAULT 0,
  amount DECIMAL(22,2) DEFAULT 0,
  turnover_rate DECIMAL(10,4) DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sector_opportunity_stock (opportunity_id, stock_code),
  KEY idx_sector_opportunity_stock_date (trade_date),
  CONSTRAINT fk_sector_opportunity_stock FOREIGN KEY (opportunity_id) REFERENCES trade_sector_opportunity(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='板块机会候选股票';
"""

PHASE_DESC = {
    "accel_up": "加速上涨 / 强势确认",
    "decel_up": "减速上涨 / 趋势衰减",
    "accel_down": "加速下跌 / 风险回避",
    "decel_down": "减速下跌 / 潜在反转观察",
    "neutral": "震荡 / 信号不明",
}


def init_sector_opportunity_schema() -> None:
    for statement in SCHEMA_SQL.split(";"):
        if statement.strip():
            execute_update(statement)
    # 兼容已存在的旧表：阶段变化事件需要纳入幂等键。
    try:
        execute_update("ALTER TABLE trade_sector_opportunity DROP INDEX uk_sector_opportunity")
    except Exception:
        pass
    try:
        execute_update("ALTER TABLE trade_sector_opportunity ADD UNIQUE KEY uk_sector_opportunity (sector_name, sector_level, trade_date, phase)")
    except Exception:
        pass


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=1)
    return (series - series.mean()) / std if pd.notna(std) and std > 0 else pd.Series(0.0, index=series.index)


def _phase(close: pd.Series) -> str:
    if len(close) < 35:
        return "neutral"
    close = pd.to_numeric(close, errors="coerce").dropna()
    if len(close) < 35:
        return "neutral"
    roc = close.iloc[-1] / close.iloc[-21] - 1
    ma20 = close.rolling(20).mean()
    slope = ma20.iloc[-1] / ma20.iloc[-3] - 1 if ma20.iloc[-3] else 0
    accel = slope - (ma20.iloc[-3] / ma20.iloc[-6] - 1 if ma20.iloc[-6] else 0)
    hist_delta = (close.pct_change().rolling(5).mean().iloc[-1] - close.pct_change().rolling(5).mean().iloc[-2])
    velocity = 1 if roc > 0.005 and slope >= 0 else -1 if roc < -0.005 and slope <= 0 else 0
    acceleration = 1 if accel > 0 and hist_delta >= 0 else -1 if accel < 0 and hist_delta <= 0 else 0
    if velocity > 0 and acceleration > 0:
        return "accel_up"
    if velocity > 0 and acceleration < 0:
        return "decel_up"
    if velocity < 0 and acceleration < 0:
        return "accel_down"
    if velocity < 0 and acceleration > 0:
        return "decel_down"
    return "neutral"


def _latest_trade_date(end_date: Optional[str] = None) -> date:
    suffix = " WHERE trade_date <= %s" if end_date else ""
    params = (end_date,) if end_date else ()
    sector_rows = execute_query("SELECT MAX(trade_date) AS trade_date FROM trade_sector_daily" + suffix, params)
    stock_rows = execute_query("SELECT MAX(trade_date) AS trade_date FROM trade_stock_daily WHERE adjustflag=2" + (" AND trade_date <= %s" if end_date else ""), params)
    sector_date = sector_rows[0]["trade_date"] if sector_rows and sector_rows[0]["trade_date"] else None
    stock_date = stock_rows[0]["trade_date"] if stock_rows and stock_rows[0]["trade_date"] else None
    if not sector_date or not stock_date:
        raise ValueError("没有可用的完整板块和前复权股票交易日数据")
    return min(sector_date, stock_date)


def _market_return_60(latest: date) -> Optional[float]:
    rows = execute_query("SELECT stock_code, trade_date, close_price FROM trade_stock_daily WHERE trade_date <= %s AND adjustflag=2 AND close_price > 0 ORDER BY stock_code, trade_date", (latest,))
    if not rows:
        return None
    frame = pd.DataFrame(rows)
    returns = []
    for _, group in frame.groupby("stock_code"):
        group = group.sort_values("trade_date")
        if len(group) >= 61 and group["trade_date"].iloc[-1] == latest:
            returns.append(float(group["close_price"].iloc[-1]) / float(group["close_price"].iloc[-61]) - 1)
    return float(np.mean(returns)) if returns else None


def _sector_frame(level: int, latest: date) -> pd.DataFrame:
    rows = execute_query(
        "SELECT sector_name, sector_level, trade_date, close_idx, total_amount, "
        "rise_count, fall_count, kline_stock_count, stock_count, top_stock, top_stock_name "
        "FROM trade_sector_daily WHERE sector_level=%s AND trade_date<=%s "
        "ORDER BY trade_date ASC",
        (level, latest),
    )
    return pd.DataFrame(rows)


def _sector_metrics(frame: pd.DataFrame, latest: date, market_return_60: Optional[float] = None) -> pd.DataFrame:
    results = []
    for name, group in frame.groupby("sector_name"):
        group = group.sort_values("trade_date").dropna(subset=["close_idx"])
        if len(group) < 70 or group["trade_date"].iloc[-1] != latest:
            continue
        close = group["close_idx"].astype(float)
        amount = group["total_amount"].fillna(0).astype(float)
        results.append({
            "sector_name": name,
            "sector_level": int(group["sector_level"].iloc[-1]),
            "trade_date": latest,
            "mom_21": close.iloc[-1] / close.iloc[-22] - 1,
            "abs_60": close.iloc[-1] / close.iloc[-61] - 1,
            "vol_ratio": amount.tail(5).mean() / amount.tail(60).mean() if amount.tail(60).mean() > 0 else 0,
            "phase": _phase(close),
            "rise_count": int(group["rise_count"].iloc[-1] or 0),
            "fall_count": int(group["fall_count"].iloc[-1] or 0),
            "total_amount": float(group["total_amount"].iloc[-1] or 0),
            "top_stock": group["top_stock"].iloc[-1] or "",
            "top_stock_name": group["top_stock_name"].iloc[-1] or "",
            "coverage": float(group["kline_stock_count"].iloc[-1] or 0) / max(float(group["stock_count"].iloc[-1] or 1), 1),
        })
    result = pd.DataFrame(results)
    if result.empty:
        return result
    # 等权市场基准的 60 日收益：每个板块先归一化，再对同一交易日等权平均。
    # 在数据完整时等价于各板块 60 日收益均值，缺失日期时仍保持时间对齐。
    benchmark = market_return_60 if market_return_60 is not None else float(result["abs_60"].mean())
    result["rs_60"] = result["abs_60"] - benchmark
    for column in ("mom_21", "rs_60", "vol_ratio"):
        result[f"{column}_z"] = _zscore(result[column])
    result["strength_score"] = result[["mom_21_z", "rs_60_z", "vol_ratio_z"]].mean(axis=1)
    result["sector_rank"] = result["strength_score"].rank(ascending=False, method="min").astype(int)
    return result.sort_values("sector_rank")


def _stock_candidates(sector_name: str, level: int, latest: date, top_n: int) -> list[dict]:
    members = get_sector_member_codes(sector_name, level=level)
    if not members:
        return []
    placeholders = ",".join(["%s"] * len(members))
    start = latest - timedelta(days=150)
    rows = execute_query(
        "SELECT d.stock_code, s.stock_name, d.trade_date, d.open_price, d.high_price, d.low_price, "
        "d.close_price, d.volume, d.amount, d.turnover_rate FROM trade_stock_daily d "
        "LEFT JOIN trade_stock_status s ON s.stock_code=d.stock_code "
        f"WHERE d.stock_code IN ({placeholders}) AND d.trade_date BETWEEN %s AND %s AND d.adjustflag=2 "
        "ORDER BY d.stock_code, d.trade_date",
        members + [start, latest],
    )
    data = pd.DataFrame(rows)
    if data.empty:
        return []
    result = []
    for code, group in data.groupby("stock_code"):
        group = group.sort_values("trade_date")
        if len(group) < 61 or group["trade_date"].iloc[-1] != latest:
            continue
        ohlc = group[["open_price", "high_price", "low_price", "close_price"]]
        if ohlc.isna().any().any():
            continue
        if ((ohlc["low_price"] > ohlc[["open_price", "high_price", "close_price"]].min(axis=1)) | (ohlc["high_price"] < ohlc[["open_price", "low_price", "close_price"]].max(axis=1))).any():
            continue
        close = group["close_price"].astype(float)
        amount = group["amount"].fillna(0).astype(float)
        last = group.iloc[-1]
        if close.iloc[-1] <= 0 or amount.tail(60).mean() <= 0 or float(last.get("amount") or 0) <= 0:
            continue
        roc_5 = close.iloc[-1] / close.iloc[-6] - 1
        roc_20 = close.iloc[-1] / close.iloc[-21] - 1
        roc_60 = close.iloc[-1] / close.iloc[-61] - 1
        ma20 = close.tail(20).mean()
        ma60 = close.tail(60).mean()
        result.append({
            "stock_code": code, "stock_name": last.get("stock_name") or code,
            "roc_5": roc_5, "roc_20": roc_20, "roc_60": roc_60,
            "vol_ratio": amount.tail(5).mean() / amount.tail(60).mean(),
            "trend_direction": "up" if roc_20 > 0 else "down",
            "ma_status": "多头排列" if last["close_price"] > ma20 > ma60 else "空头排列" if last["close_price"] < ma20 < ma60 else "均线缠绕",
            "close_price": float(last["close_price"]), "volume": int(last["volume"] or 0),
            "amount": float(last["amount"] or 0), "turnover_rate": last.get("turnover_rate"),
        })
    if not result:
        return []
    candidates = pd.DataFrame(result)
    candidates["stock_score"] = candidates["roc_20"] * 0.4 + candidates["roc_60"] * 0.3 + candidates["roc_5"] * 0.3
    candidates = candidates.sort_values("stock_score", ascending=False).head(top_n)
    candidates["stock_rank"] = range(1, len(candidates) + 1)
    return candidates.replace({np.nan: None}).to_dict("records")


def _confirmation(sector_name: str, level: int, latest: date) -> tuple[str, int]:
    previous_trade = execute_query(
        "SELECT MAX(trade_date) AS trade_date FROM trade_sector_daily WHERE trade_date < %s",
        (latest,),
    )
    previous_date = previous_trade[0]["trade_date"] if previous_trade and previous_trade[0]["trade_date"] else None
    rows = execute_query(
        "SELECT trade_date, confirmation_days FROM trade_sector_opportunity "
        "WHERE sector_name=%s AND sector_level=%s AND trade_date<%s ORDER BY trade_date DESC LIMIT 1",
        (sector_name, level, latest),
    )
    days = int(rows[0]["confirmation_days"] or 0) + 1 if rows and previous_date and rows[0]["trade_date"] == previous_date else 1
    return ("确认机会" if days >= 3 else "持续确认" if days == 2 else "首次出现", days)


def scan_sector_opportunities(level: int = 2, end_date: Optional[str] = None, top_n: int = 5, top_sector_n: int = 10, sector_names: Optional[list[str]] = None) -> dict:
    if level != 2:
        raise ValueError("板块扫描仅支持申万二级板块")
    valid_names = set(list_sectors_from_db(level=2))
    selected_names = None
    if sector_names:
        selected_names = [name.strip() for name in sector_names if name and name.strip()]
        invalid_names = [name for name in selected_names if name not in valid_names]
        if invalid_names:
            raise ValueError(f"以下板块不是有效的申万二级板块：{'、'.join(invalid_names)}")
        if not selected_names:
            raise ValueError("请至少输入一个申万二级板块名称")
    if level not in (1, 2):
        raise ValueError("sector level must be 1 or 2")
    if top_n < 1 or top_n > 50 or top_sector_n < 1 or top_sector_n > 100:
        raise ValueError("top_n/top_sector_n 参数超出范围")
    latest = _latest_trade_date(end_date)
    metrics = _sector_metrics(_sector_frame(level, latest), latest, _market_return_60(latest))
    if selected_names is not None:
        metrics = metrics[metrics["sector_name"].isin(selected_names)].copy()
        if metrics.empty:
            raise ValueError("输入的申万二级板块在当前交易日没有可用分析数据")
        metrics["sector_rank"] = metrics["strength_score"].rank(method="min", ascending=False).astype(int)
    if metrics.empty:
        return {"source": "trade_sector_daily", "trade_date": str(latest), "created": 0, "skipped": 0, "data_quality": "insufficient"}
    eligible = metrics[(metrics["sector_rank"] <= top_sector_n) & (metrics["phase"] == "accel_up") & (metrics["mom_21"] > 0) & (metrics["rs_60"] > 0) & (metrics["vol_ratio"] >= 1.0) & (metrics["coverage"] >= 0.6)]
    eligible_names = set(eligible["sector_name"].tolist())
    created = 0
    candidates_count = 0
    # 持久化所有板块的分析结果；机会门禁只决定是否生成候选股票。
    for item in metrics.to_dict("records"):
        is_eligible = item["sector_name"] in eligible_names
        # 每个板块都计算板块内候选，机会门禁仅用于标记是否达到正式机会条件。
        candidates = _stock_candidates(item["sector_name"], level, latest, top_n)
        confirmation_status, confirmation_days = _confirmation(item["sector_name"], level, latest) if is_eligible else ("未触发", 0)
        reason = {
            "rules": ["phase=accel_up", "sector_rank<=top_sector_n", "mom_21>0", "rs_60>0", "vol_ratio>=1", "coverage>=0.6"],
            "coverage": item["coverage"],
            "top_n": top_n,
            "eligible": is_eligible,
        }
        opportunity_sql = """
        INSERT INTO trade_sector_opportunity
        (sector_name, sector_level, trade_date, phase, phase_desc, strength_score, sector_rank,
         mom_21, rs_60, vol_ratio, rise_count, fall_count, total_amount, top_stock, top_stock_name,
         confirmation_status, confirmation_days, reason)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE phase=VALUES(phase), phase_desc=VALUES(phase_desc), strength_score=VALUES(strength_score),
         sector_rank=VALUES(sector_rank), mom_21=VALUES(mom_21), rs_60=VALUES(rs_60), vol_ratio=VALUES(vol_ratio),
         rise_count=VALUES(rise_count), fall_count=VALUES(fall_count), total_amount=VALUES(total_amount),
         top_stock=VALUES(top_stock), top_stock_name=VALUES(top_stock_name), confirmation_status=VALUES(confirmation_status),
         confirmation_days=VALUES(confirmation_days), reason=VALUES(reason)
        """
        execute_update(opportunity_sql, (item["sector_name"], level, latest, item["phase"], PHASE_DESC[item["phase"]], item["strength_score"], item["sector_rank"], item["mom_21"], item["rs_60"], item["vol_ratio"], item["rise_count"], item["fall_count"], item["total_amount"], item["top_stock"], item["top_stock_name"], confirmation_status, confirmation_days, json.dumps(reason, ensure_ascii=False)))
        opportunity = execute_query("SELECT id FROM trade_sector_opportunity WHERE sector_name=%s AND sector_level=%s AND trade_date=%s AND phase=%s", (item["sector_name"], level, latest, item["phase"]))
        if not opportunity:
            continue
        opportunity_id = opportunity[0]["id"]
        if candidates:
            execute_many("""
        INSERT INTO trade_sector_opportunity_stock
        (opportunity_id, sector_name, sector_level, trade_date, stock_code, stock_name, stock_rank, stock_score,
         roc_5, roc_20, roc_60, vol_ratio, trend_direction, ma_status, close_price, volume, amount, turnover_rate)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE stock_name=VALUES(stock_name), stock_rank=VALUES(stock_rank), stock_score=VALUES(stock_score),
         roc_5=VALUES(roc_5), roc_20=VALUES(roc_20), roc_60=VALUES(roc_60), vol_ratio=VALUES(vol_ratio),
         trend_direction=VALUES(trend_direction), ma_status=VALUES(ma_status), close_price=VALUES(close_price),
         volume=VALUES(volume), amount=VALUES(amount), turnover_rate=VALUES(turnover_rate)
        """, [(opportunity_id, item["sector_name"], level, latest, candidate["stock_code"], candidate["stock_name"], candidate["stock_rank"], candidate["stock_score"], candidate["roc_5"], candidate["roc_20"], candidate["roc_60"], candidate["vol_ratio"], candidate["trend_direction"], candidate["ma_status"], candidate["close_price"], candidate["volume"], candidate["amount"], candidate["turnover_rate"]) for candidate in candidates])
        created += 1
        candidates_count += len(candidates)
    return {"source": "trade_sector_daily", "trade_date": str(latest), "level": level, "created": created, "candidate_count": candidates_count, "eligible_sector_count": len(eligible), "data_quality": "ok"}


def list_sector_opportunities(level: Optional[int] = None, sector_name: Optional[str] = None, phase: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None, page: int = 1, page_size: int = 20, min_rank: Optional[int] = None, max_rank: Optional[int] = None, min_stock_score: Optional[float] = None) -> dict:
    conditions, params = [], []
    if level:
        conditions.append("sector_level=%s"); params.append(level)
    if sector_name:
        conditions.append("sector_name LIKE %s"); params.append(f"%{sector_name}%")
    if phase:
        conditions.append("phase=%s"); params.append(phase)
    if start_date:
        conditions.append("trade_date>=%s"); params.append(start_date)
    if end_date:
        conditions.append("trade_date<=%s"); params.append(end_date)
    if min_rank is not None:
        conditions.append("sector_rank>=%s"); params.append(min_rank)
    if max_rank is not None:
        conditions.append("sector_rank<=%s"); params.append(max_rank)
    if min_stock_score is not None:
        conditions.append("EXISTS (SELECT 1 FROM trade_sector_opportunity_stock os WHERE os.opportunity_id=trade_sector_opportunity.id AND os.stock_score >= %s)"); params.append(min_stock_score)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    total = execute_query("SELECT COUNT(*) AS total FROM trade_sector_opportunity" + where, params)[0]["total"]
    rows = execute_query("SELECT * FROM trade_sector_opportunity" + where + " ORDER BY trade_date DESC, sector_rank ASC LIMIT %s OFFSET %s", params + [page_size, (page - 1) * page_size])
    return {"count": total, "page": page, "page_size": page_size, "data": rows}


def get_sector_opportunity_candidates(opportunity_id: int) -> list[dict]:
    candidates = execute_query("SELECT * FROM trade_sector_opportunity_stock WHERE opportunity_id=%s ORDER BY stock_rank", (opportunity_id,))
    if candidates:
        return candidates
    opportunity = execute_query("SELECT sector_name, sector_level, trade_date FROM trade_sector_opportunity WHERE id=%s", (opportunity_id,))
    if not opportunity:
        return []
    item = opportunity[0]
    # 兼容旧扫描记录：候选表为空时按当日数据即时补算，避免详情出现空列表。
    return _stock_candidates(item["sector_name"], int(item["sector_level"]), item["trade_date"], 5)


def list_sector_opportunity_history(sector_name: Optional[str] = None, level: Optional[int] = None, start_date: Optional[str] = None, end_date: Optional[str] = None, confirmation_status: Optional[str] = None) -> list[dict]:
    conditions, params = [], []
    if sector_name:
        conditions.append("sector_name LIKE %s")
        params.append(f"%{sector_name}%")
    for column, value, operator in (("sector_level", level, "="), ("trade_date", start_date, ">="), ("trade_date", end_date, "<="), ("confirmation_status", confirmation_status, "=")):
        if value is not None:
            conditions.append(f"{column}{operator}%s")
            params.append(value)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return execute_query("SELECT * FROM trade_sector_opportunity" + where + " ORDER BY trade_date DESC, sector_rank ASC", params)


def get_sector_opportunity(opportunity_id: int) -> dict:
    rows = execute_query("SELECT * FROM trade_sector_opportunity WHERE id=%s", (opportunity_id,))
    if not rows:
        raise ValueError("未找到板块机会")
    item = rows[0]
    item["reason"] = json.loads(item["reason"]) if item.get("reason") else {}
    item["candidates"] = get_sector_opportunity_candidates(opportunity_id)
    return item
