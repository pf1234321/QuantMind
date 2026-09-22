"""交易计划 MySQL 持久化存储。"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.database import get_connection


class TradePlanStore:
    """交易计划仓储，兼容从旧 JSONL 文件导入历史数据。"""

    def __init__(self, path: str | Path = "data/trade_plans.jsonl"):
        self.path = Path(path)
        self.ensure_schema()

    @staticmethod
    def ensure_schema() -> None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trade_plan (
                        id VARCHAR(64) NOT NULL PRIMARY KEY,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        stock_code VARCHAR(32) NOT NULL,
                        action VARCHAR(10) NOT NULL,
                        target_weight DECIMAL(8,6) NULL,
                        reason TEXT NULL,
                        signal_id VARCHAR(128) NULL,
                        signal_date VARCHAR(32) NULL,
                        risk_decision VARCHAR(12) NULL,
                        risk_level VARCHAR(20) NULL,
                        risk_snapshot_json LONGTEXT NULL,
                        created_at DATETIME(6) NOT NULL,
                        updated_at DATETIME(6) NOT NULL,
                        INDEX idx_trade_plan_status (status),
                        INDEX idx_trade_plan_stock_code (stock_code),
                        INDEX idx_trade_plan_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            conn.commit()
            TradePlanStore._ensure_risk_columns(conn)
        finally:
            conn.close()

    @staticmethod
    def _ensure_risk_columns(conn) -> None:
        """为已有部署补充风控字段，重复执行安全。"""
        columns = (
            ("risk_decision", "VARCHAR(12) NULL"),
            ("risk_level", "VARCHAR(20) NULL"),
            ("risk_snapshot_json", "LONGTEXT NULL"),
        )
        with conn.cursor() as cur:
            for name, definition in columns:
                try:
                    cur.execute(f"ALTER TABLE trade_plan ADD COLUMN {name} {definition}")
                except Exception:
                    conn.rollback()
        conn.commit()

    def migrate_jsonl(self) -> int:
        """将旧 JSONL 记录幂等导入 MySQL，原文件保留作备份。"""
        if not self.path.exists():
            return 0

        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        if not rows:
            return 0

        conn = get_connection()
        imported = 0
        try:
            with conn.cursor() as cur:
                for row in rows:
                    created_at = _parse_datetime(row.get("created_at"))
                    updated_at = _parse_datetime(row.get("updated_at")) or created_at
                    cur.execute(
                        """
                        INSERT IGNORE INTO trade_plan
                        (id, status, stock_code, action, target_weight, reason,
                         signal_id, signal_date, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            row["id"],
                            row.get("status", "pending"),
                            row["stock_code"],
                            row["action"],
                            row.get("target_weight"),
                            row.get("reason"),
                            row.get("signal_id"),
                            row.get("signal_date"),
                            created_at or datetime.now(timezone.utc).replace(tzinfo=None),
                            updated_at or datetime.now(timezone.utc).replace(tzinfo=None),
                        ),
                    )
                    imported += cur.rowcount
            conn.commit()
            return imported
        finally:
            conn.close()

    def list(
        self,
        status: str | None = None,
        stock_code: str | None = None,
        action: str | None = None,
        stock_keyword: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=%s")
            params.append(status)
        if stock_code:
            clauses.append("stock_code=%s")
            params.append(stock_code)
        if action:
            clauses.append("action=%s")
            params.append(action)
        if stock_keyword:
            clauses.append("stock_code LIKE %s")
            params.append(f"%{stock_keyword}%")
        if start_date:
            clauses.append("signal_date >= %s")
            params.append(start_date)
        if end_date:
            clauses.append("signal_date <= %s")
            params.append(end_date)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM trade_plan{where} ORDER BY created_at DESC", params)
                return list(cur.fetchall())
        finally:
            conn.close()

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        plan_id = _next_plan_id()
        item = {
            "id": plan_id,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            **payload,
        }
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO trade_plan
                    (id, status, stock_code, action, target_weight, reason,
                     signal_id, signal_date, risk_decision, risk_level, risk_snapshot_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        item["id"], item["status"], item["stock_code"], item["action"],
                        item.get("target_weight"), item.get("reason"), item.get("signal_id"),
                        item.get("signal_date"), item.get("risk_decision"), item.get("risk_level"),
                        item.get("risk_snapshot_json"), item["created_at"], item["updated_at"],
                    ),
                )
            conn.commit()
            return item
        finally:
            conn.close()

    def get(self, plan_id: str) -> dict[str, Any] | None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM trade_plan WHERE id=%s", (plan_id,))
                return cur.fetchone()
        finally:
            conn.close()

    def update_risk(self, plan_id: str, risk: dict[str, Any]) -> dict[str, Any] | None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE trade_plan SET risk_decision=%s, risk_level=%s, risk_snapshot_json=%s, updated_at=%s WHERE id=%s",
                    (risk.get("decision"), risk.get("risk_level"), json.dumps(risk, ensure_ascii=False, default=str), datetime.now(timezone.utc).replace(tzinfo=None), plan_id),
                )
                cur.execute("SELECT * FROM trade_plan WHERE id=%s", (plan_id,))
                item = cur.fetchone()
            conn.commit()
            return item
        finally:
            conn.close()

    def update_status(self, plan_id: str, status: str) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE trade_plan SET status=%s, updated_at=%s WHERE id=%s",
                    (status, now, plan_id),
                )
                if cur.rowcount == 0:
                    conn.rollback()
                    return None
                cur.execute("SELECT * FROM trade_plan WHERE id=%s", (plan_id,))
                item = cur.fetchone()
            conn.commit()
            return item
        finally:
            conn.close()


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _next_plan_id() -> str:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM trade_plan ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
        if not row:
            return "plan-000001"
        try:
            number = int(str(row["id"]).rsplit("-", 1)[-1]) + 1
        except ValueError:
            number = 1
        return f"plan-{number:06d}"
    finally:
        conn.close()


def init_trade_plan_schema() -> int:
    """初始化交易计划表并导入旧数据，供应用启动阶段调用。"""
    store = TradePlanStore()
    return store.migrate_jsonl()
