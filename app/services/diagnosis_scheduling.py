"""诊断计划和通知的研究域基础服务。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.database import execute_update


def _fingerprint(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def init_schema() -> None:
    execute_update("""CREATE TABLE IF NOT EXISTS diagnosis_schedule (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, user_id VARCHAR(64) NOT NULL,
        name VARCHAR(100) NOT NULL, target_json JSON NOT NULL, cron_expr VARCHAR(100) NOT NULL,
        timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai', status VARCHAR(20) NOT NULL DEFAULT 'active',
        agent_types JSON NULL, retry_limit INT NOT NULL DEFAULT 2, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    execute_update("""CREATE TABLE IF NOT EXISTS diagnosis_notification (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, user_id VARCHAR(64) NOT NULL,
        diagnosis_id VARCHAR(64) NOT NULL, report_version VARCHAR(40) NOT NULL, channel VARCHAR(20) NOT NULL,
        recipient VARCHAR(255) NOT NULL, trigger_name VARCHAR(60) NOT NULL, idempotency_key VARCHAR(128) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'queued', attempts INT NOT NULL DEFAULT 0, last_error TEXT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        UNIQUE KEY uq_diagnosis_notification (idempotency_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")


def make_idempotency_key(diagnosis_id: str, report_version: str, channel: str, recipient: str, trigger: str) -> str:
    return _fingerprint({"diagnosis_id": diagnosis_id, "report_version": report_version, "channel": channel, "recipient": recipient, "trigger": trigger})


def notification_payload(diagnosis_id: str, report: dict[str, Any], channel: str, recipient: str, trigger: str) -> dict[str, Any]:
    version = str(report.get("report_version", "unknown"))
    return {"diagnosis_id": diagnosis_id, "report_version": version, "channel": channel, "recipient": recipient, "trigger": trigger, "idempotency_key": make_idempotency_key(diagnosis_id, version, channel, recipient, trigger), "message": "个股诊断报告已生成，仅供研究辅助，不构成投资建议。", "created_at": datetime.now().isoformat()}
