"""诊断研究域的自选股与历史诊断回测配置转换。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.database import execute_query, execute_update


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def init_schema() -> None:
    execute_update("""CREATE TABLE IF NOT EXISTS diagnosis_watchlist (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, user_id VARCHAR(64) NOT NULL,
        name VARCHAR(100) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        UNIQUE KEY uq_watchlist_user_name (user_id, name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    execute_update("""CREATE TABLE IF NOT EXISTS diagnosis_watchlist_item (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, watchlist_id BIGINT NOT NULL,
        stock_code VARCHAR(32) NOT NULL, stock_name VARCHAR(100) NULL, note VARCHAR(500) NULL,
        sort_order INT NOT NULL DEFAULT 0, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        UNIQUE KEY uq_watchlist_stock (watchlist_id, stock_code), KEY idx_watchlist (watchlist_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    execute_update("""CREATE TABLE IF NOT EXISTS diagnosis_backtest_link (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, user_id VARCHAR(64) NOT NULL,
        diagnosis_id VARCHAR(64) NOT NULL, snapshot_version VARCHAR(40) NOT NULL,
        config_json JSON NOT NULL, input_fingerprint VARCHAR(64) NOT NULL,
        status VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL,
        UNIQUE KEY uq_diagnosis_backtest (user_id, diagnosis_id, snapshot_version, input_fingerprint)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")


def create_backtest_config(user_id: str, diagnosis_id: str, snapshot: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    config = {"diagnosis_id": diagnosis_id, "snapshot_version": snapshot.get("report_version", "unknown"), "signal": snapshot.get("consensus"), "risk_reward": snapshot.get("risk_reward"), "start_date": params.get("start_date"), "end_date": params.get("end_date"), "cost": params.get("cost", 0), "slippage": params.get("slippage", 0), "benchmark": params.get("benchmark"), "data_version": params.get("data_version"), "lookahead_check": "required"}
    return {"user_id": user_id, "config": config, "input_fingerprint": _fingerprint(config), "status": "created", "disclaimer": "仅用于历史模拟，不构成投资建议。"}
