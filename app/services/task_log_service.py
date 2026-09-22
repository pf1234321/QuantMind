# -*- coding: utf-8 -*-
"""数据同步任务执行日志服务（表: sync_task_log）

记录每次同步任务的执行情况：触发方式、状态、耗时、影响行数、结果摘要、异常信息。
供调度器(app/scheduler.py)与同步 API 共用。
"""
import json
import logging
from datetime import datetime
from typing import Optional

from app.database import execute_query, execute_update

logger = logging.getLogger(__name__)

# 结果摘要最大长度（防止 message 过长）
MAX_MESSAGE_LEN = 4000


def start_log(task_name: str, trigger: str = "manual") -> int:
    """记录任务开始，返回日志 id（status=running）"""
    sql = (
        "INSERT INTO sync_task_log (task_name, `trigger`, status, started_at) "
        "VALUES (%s, %s, 'running', %s)"
    )
    conn_affected = execute_update(sql, (task_name, trigger, datetime.now()))
    if conn_affected <= 0:
        raise RuntimeError("写入 sync_task_log 失败")
    row = execute_query(
        "SELECT id FROM sync_task_log WHERE task_name=%s AND status='running' "
        "ORDER BY id DESC LIMIT 1",
        (task_name,),
    )
    return int(row[0]["id"]) if row else 0


def finish_log(
    log_id: int,
    status: str,
    message: Optional[str] = None,
    rows_affected: Optional[int] = None,
    error: Optional[str] = None,
    started_at: Optional[datetime] = None,
) -> None:
    """更新任务结束状态（success/failed/skipped）"""
    finished_at = datetime.now()
    duration_ms = None
    if started_at is not None:
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    if message and len(message) > MAX_MESSAGE_LEN:
        message = message[:MAX_MESSAGE_LEN] + "...(truncated)"
    if error and len(error) > MAX_MESSAGE_LEN:
        error = error[:MAX_MESSAGE_LEN] + "...(truncated)"
    sql = (
        "UPDATE sync_task_log SET status=%s, finished_at=%s, duration_ms=%s, "
        "rows_affected=%s, message=%s, error=%s WHERE id=%s"
    )
    execute_update(
        sql, (status, finished_at, duration_ms, rows_affected, message, error, log_id)
    )


def _extract_rows_affected(result) -> Optional[int]:
    """从同步结果 dict 中提取影响/写入行数"""
    if isinstance(result, dict):
        for key in ("written", "total", "rows", "updated", "stocks", "inserted"):
            val = result.get(key)
            if isinstance(val, int) and val >= 0:
                return val
    return None


def to_message(result) -> Optional[str]:
    """将同步结果转为可存库的 JSON 摘要"""
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


def list_logs(
    task_name: Optional[str] = None,
    status: Optional[str] = None,
    started_after: Optional[str] = None,
    started_before: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict]]:
    """按条件分页查询执行日志，返回匹配总数和当前页数据。"""
    where, params = [], []
    if task_name:
        where.append("task_name = %s")
        params.append(task_name)
    if status:
        where.append("status = %s")
        params.append(status)
    if started_after:
        where.append("started_at >= %s")
        params.append(started_after)
    if started_before:
        where.append("started_at <= %s")
        params.append(started_before)
    cond = ("WHERE " + " AND ".join(where)) if where else ""
    count_rows = execute_query(f"SELECT COUNT(*) AS total FROM sync_task_log {cond}", params)
    total = int(count_rows[0]["total"]) if count_rows else 0
    sql = (
        f"SELECT id, task_name, `trigger`, status, started_at, finished_at, "
        f"duration_ms, rows_affected, message, error "
        f"FROM sync_task_log {cond} ORDER BY started_at DESC, id DESC LIMIT %s OFFSET %s"
    )
    page_params = params + [int(limit), int(offset)]
    return total, execute_query(sql, page_params)


def get_log(log_id: int) -> Optional[dict]:
    rows = execute_query(
        "SELECT id, task_name, `trigger`, status, started_at, finished_at, "
        "duration_ms, rows_affected, message, error "
        "FROM sync_task_log WHERE id=%s",
        (log_id,),
    )
    return rows[0] if rows else None


def latest_status(task_name: str) -> Optional[dict]:
    """查询某任务最近一次执行记录（供接口展示）"""
    rows = execute_query(
        "SELECT id, `trigger`, status, started_at, finished_at, duration_ms, "
        "rows_affected, message, error FROM sync_task_log "
        "WHERE task_name=%s ORDER BY id DESC LIMIT 1",
        (task_name,),
    )
    return rows[0] if rows else None


def summary() -> list[dict]:
    """每个任务最近执行概况（dashboard 用）"""
    return execute_query(
        "SELECT task_name, "
        "  COUNT(*) AS run_count, "
        "  SUM(status='success') AS success_count, "
        "  SUM(status='failed') AS failed_count, "
        "  SUM(status='running') AS running_count, "
        "  COALESCE(ROUND(AVG(duration_ms)), 0) AS avg_duration_ms, "
        "  MAX(started_at) AS last_run "
        "FROM sync_task_log GROUP BY task_name ORDER BY task_name"
    )


def overview() -> dict:
    """返回同步中心的聚合健康指标。"""
    rows = execute_query(
        "SELECT COUNT(*) AS total, "
        "SUM(status='success') AS success_count, "
        "SUM(status='failed') AS failed_count, "
        "SUM(status='running') AS running_count, "
        "MAX(started_at) AS last_run "
        "FROM sync_task_log WHERE started_at >= CURRENT_DATE"
    )
    row = rows[0] if rows else {}
    total = int(row.get('total') or 0)
    success = int(row.get('success_count') or 0)
    return {
        "today_runs": total,
        "success_count": success,
        "failed_count": int(row.get('failed_count') or 0),
        "running_count": int(row.get('running_count') or 0),
        "success_rate": round(success * 100 / total, 1) if total else None,
        "last_run": row.get('last_run'),
        "summary": summary(),
    }
