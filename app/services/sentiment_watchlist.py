# -*- coding: utf-8 -*-
"""舆情监控列表服务（CRUD + 阈值告警）。

监控列表与 `diagnosis_watchlist` 独立，专门服务于"舆情分析师"页面：
- 支持按分组管理（默认 default），每个 (group, stock_code) 唯一
- 阈值字段：FGI 低/高阈值、负面新闻数阈值
- 告警接口对比 `sentiment_aggregate` 最新行与监控阈值

数据全部基于现有 sentiment_* / fear_index_history / market_events 表，
本服务不引入新的同步任务，复用 `sentiment_sync` 已有的调度。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from app.database import execute_many, execute_query, execute_update

logger = logging.getLogger(__name__)


def init_schema() -> None:
    """建表（幂等）；通常由 lifespan 钩子调用。"""
    execute_update(
        """CREATE TABLE IF NOT EXISTS sentiment_watchlist (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            group_name VARCHAR(64) NOT NULL DEFAULT 'default',
            stock_code VARCHAR(32) NOT NULL,
            stock_name VARCHAR(64) NULL,
            threshold_fgi_low INT NULL,
            threshold_fgi_high INT NULL,
            threshold_negative_count INT NULL,
            note VARCHAR(255) NULL,
            enabled TINYINT(1) NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            UNIQUE KEY uq_watchlist_group_stock (group_name, stock_code),
            KEY idx_watchlist_enabled (enabled)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "group_name": row.get("group_name"),
        "stock_code": row.get("stock_code"),
        "stock_name": row.get("stock_name"),
        "threshold_fgi_low": row.get("threshold_fgi_low"),
        "threshold_fgi_high": row.get("threshold_fgi_high"),
        "threshold_negative_count": row.get("threshold_negative_count"),
        "note": row.get("note"),
        "enabled": bool(row.get("enabled")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def add_watch(
    group: str,
    stock_code: str,
    stock_name: str | None = None,
    threshold_fgi_low: int | None = None,
    threshold_fgi_high: int | None = None,
    threshold_negative_count: int | None = None,
    note: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """添加监控项；已存在则更新关键字段。"""
    code = str(stock_code).strip().split(".")[0]
    if not code:
        raise ValueError("stock_code 不能为空")
    now = _now()
    execute_update(
        """INSERT INTO sentiment_watchlist
            (group_name, stock_code, stock_name, threshold_fgi_low, threshold_fgi_high,
             threshold_negative_count, note, enabled, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                stock_name=VALUES(stock_name),
                threshold_fgi_low=VALUES(threshold_fgi_low),
                threshold_fgi_high=VALUES(threshold_fgi_high),
                threshold_negative_count=VALUES(threshold_negative_count),
                note=VALUES(note),
                enabled=VALUES(enabled),
                updated_at=VALUES(updated_at)""",
        (
            group or "default",
            code,
            stock_name,
            threshold_fgi_low,
            threshold_fgi_high,
            threshold_negative_count,
            note,
            1 if enabled else 0,
            now,
            now,
        ),
    )
    row = execute_query(
        "SELECT * FROM sentiment_watchlist WHERE group_name=%s AND stock_code=%s LIMIT 1",
        (group or "default", code),
    )
    return _decode_row(row[0]) if row else {"stock_code": code, "group_name": group}


def remove_watch(group: str, stock_code: str) -> bool:
    affected = execute_update(
        "DELETE FROM sentiment_watchlist WHERE group_name=%s AND stock_code=%s",
        (group or "default", str(stock_code).strip()),
    )
    return bool(affected)


def update_watch(group: str, stock_code: str, **fields: Any) -> dict[str, Any] | None:
    """部分字段更新。"""
    allowed = {"stock_name", "threshold_fgi_low", "threshold_fgi_high",
               "threshold_negative_count", "note", "enabled"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return _get(group, stock_code)
    if "enabled" in updates:
        updates["enabled"] = 1 if updates["enabled"] else 0
    sets = ", ".join(f"{k}=%s" for k in updates)
    params = [*updates.values(), _now(), group or "default", str(stock_code).strip()]
    execute_update(
        f"UPDATE sentiment_watchlist SET {sets}, updated_at=%s WHERE group_name=%s AND stock_code=%s",
        params,
    )
    return _get(group, stock_code)


def _get(group: str, stock_code: str) -> dict[str, Any] | None:
    rows = execute_query(
        "SELECT * FROM sentiment_watchlist WHERE group_name=%s AND stock_code=%s LIMIT 1",
        (group or "default", str(stock_code).strip()),
    )
    return _decode_row(rows[0]) if rows else None


def list_watch(group: str | None = None, enabled_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM sentiment_watchlist"
    params: list[Any] = []
    conds: list[str] = []
    if group:
        conds.append("group_name=%s")
        params.append(group)
    if enabled_only:
        conds.append("enabled=1")
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY updated_at DESC"
    rows = execute_query(sql, params)
    return [_decode_row(r) for r in rows]


def _latest_aggregate(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """取每只股票最新一条 sentiment_aggregate -> {stock_code: row}"""
    if not stock_codes:
        return {}
    placeholders = ",".join(["%s"] * len(stock_codes))
    rows = execute_query(
        f"""SELECT a.stock_code, a.fear_greed_index, a.overall_sentiment,
                   a.positive_count, a.negative_count, a.neutral_count,
                   a.top_themes, a.risk_alerts, a.opportunity_hints,
                   a.summary, a.analyzed_at
            FROM sentiment_aggregate a
            INNER JOIN (
                SELECT stock_code, MAX(analyzed_at) AS mx
                FROM sentiment_aggregate
                WHERE stock_code IN ({placeholders})
                GROUP BY stock_code
            ) m ON a.stock_code=m.stock_code AND a.analyzed_at=m.mx""",
        stock_codes,
    )
    return {r["stock_code"]: r for r in rows}


def check_thresholds(group: str = "default") -> list[dict[str, Any]]:
    """扫描监控列表，比对 sentiment_aggregate 最新行 + 阈值，返回超阈值告警列表。"""
    watches = list_watch(group=group, enabled_only=True)
    if not watches:
        return []
    aggregates = _latest_aggregate([w["stock_code"] for w in watches])
    alerts: list[dict[str, Any]] = []
    for w in watches:
        agg = aggregates.get(w["stock_code"])
        if not agg:
            alerts.append({
                "stock_code": w["stock_code"],
                "stock_name": w.get("stock_name"),
                "alert_type": "no_data",
                "level": "warning",
                "message": "监控列表中存在股票但暂无情绪聚合数据，建议先执行 sentiment 同步任务。",
                "current": None,
                "threshold": {
                    "fgi_low": w.get("threshold_fgi_low"),
                    "fgi_high": w.get("threshold_fgi_high"),
                    "negative_count": w.get("threshold_negative_count"),
                },
            })
            continue
        fgi = agg.get("fear_greed_index")
        neg = agg.get("negative_count") or 0
        reasons: list[str] = []
        level = "info"
        low, high, neg_th = w.get("threshold_fgi_low"), w.get("threshold_fgi_high"), w.get("threshold_negative_count")
        if low is not None and fgi is not None and fgi < low:
            reasons.append(f"FGI {fgi} 低于阈值 {low}")
            level = "danger"
        if high is not None and fgi is not None and fgi > high:
            reasons.append(f"FGI {fgi} 高于阈值 {high}")
            level = "danger" if level != "danger" else level
        if neg_th is not None and neg >= neg_th:
            reasons.append(f"负面新闻 {neg} 条达到阈值 {neg_th}")
            level = "danger" if level != "danger" else level
        if reasons:
            alerts.append({
                "stock_code": w["stock_code"],
                "stock_name": w.get("stock_name") or agg.get("stock_name"),
                "alert_type": "threshold_breach",
                "level": level,
                "message": "；".join(reasons),
                "current": {
                    "fear_greed_index": fgi,
                    "overall_sentiment": agg.get("overall_sentiment"),
                    "positive_count": agg.get("positive_count"),
                    "negative_count": neg,
                    "neutral_count": agg.get("neutral_count"),
                    "analyzed_at": agg.get("analyzed_at"),
                },
                "threshold": {"fgi_low": low, "fgi_high": high, "negative_count": neg_th},
            })
    return alerts


def _latest_fear_index() -> dict[str, Any] | None:
    rows = execute_query(
        "SELECT vix, ovx, gvz, us10y, composite_score, risk_level, suggestion, recorded_at "
        "FROM fear_index_history ORDER BY recorded_at DESC LIMIT 1"
    )
    return rows[0] if rows else None


def _latest_high_severity_events(limit: int = 10) -> list[dict[str, Any]]:
    """近期高严重度（强烈关注/坚决回避）市场事件。"""
    rows = execute_query(
        """SELECT stock_code, event_type, event_subtype, event_desc, `signal`, news_date
           FROM market_events
           WHERE `signal` IN ('强烈关注', '坚决回避')
           ORDER BY created_at DESC LIMIT %s""",
        (limit,),
    )
    return list(rows)


def get_alerts(group: str = "default") -> dict[str, Any]:
    """聚合：监控阈值告警 + 最新恐慌指数 + 重大事件。"""
    threshold_alerts = check_thresholds(group)
    fear = _latest_fear_index()
    events = _latest_high_severity_events()
    market_alert: dict[str, Any] | None = None
    if fear:
        score = fear.get("composite_score")
        risk = fear.get("risk_level") or ""
        market_alert = {
            "source": "fear_index_history",
            "composite_score": score,
            "risk_level": risk,
            "vix": fear.get("vix"),
            "us10y": fear.get("us10y"),
            "suggestion": fear.get("suggestion"),
            "recorded_at": fear.get("recorded_at"),
            "is_panic": score is not None and score < 30,
            "is_greed": score is not None and score > 75,
            "label": risk,
        }
    return {
        "threshold_alerts": threshold_alerts,
        "market_alert": market_alert,
        "high_severity_events": events,
        "summary": {
            "threshold_breach_count": sum(1 for a in threshold_alerts if a.get("alert_type") == "threshold_breach"),
            "no_data_count": sum(1 for a in threshold_alerts if a.get("alert_type") == "no_data"),
            "market_panic": bool(market_alert and market_alert["is_panic"]),
            "event_count": len(events),
        },
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }