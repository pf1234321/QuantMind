# -*- coding: utf-8 -*-
"""数据库连接层：基于 PyMySQL 的同步连接 + 常用 SQL 工具函数
（从课程 02/11 周 db_config.py 迁移并统一）
"""
from typing import Any, Iterable, Optional
import logging
import time

import pymysql
from pymysql.cursors import DictCursor

from app.config import settings


logger = logging.getLogger("quantmind.database")


def _sql_kind(sql: str) -> str:
    return sql.lstrip().split(None, 1)[0].upper() if sql.strip() else "UNKNOWN"


def get_connection() -> pymysql.Connection:
    """获取一个新的数据库连接（调用方负责 close）"""
    return pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


def execute_query(sql: str, params: Optional[Iterable[Any]] = None) -> list[dict]:
    """执行查询，记录 SQL 类型、耗时和结果数量，不记录参数明文。"""
    started_at = time.perf_counter()
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                rows = list(cur.fetchall())
                logger.info("db_query kind=%s rows=%s duration_ms=%.2f", _sql_kind(sql), len(rows), (time.perf_counter() - started_at) * 1000)
                return rows
        finally:
            conn.close()
    except Exception:
        logger.exception("db_query_failed kind=%s duration_ms=%.2f", _sql_kind(sql), (time.perf_counter() - started_at) * 1000)
        raise


def execute_update(sql: str, params: Optional[Iterable[Any]] = None) -> int:
    """执行写操作并记录 SQL 类型、耗时和影响行数。"""
    started_at = time.perf_counter()
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(sql, params or ())
            conn.commit()
            affected = affected or 0
            logger.info("db_update kind=%s affected=%s duration_ms=%.2f", _sql_kind(sql), affected, (time.perf_counter() - started_at) * 1000)
            return affected
        finally:
            conn.close()
    except Exception:
        logger.exception("db_update_failed kind=%s duration_ms=%.2f", _sql_kind(sql), (time.perf_counter() - started_at) * 1000)
        raise


def execute_many(sql: str, rows: Iterable[Iterable[Any]]) -> int:
    """批量执行并记录 SQL 类型、批次大小、耗时和影响行数。"""
    started_at = time.perf_counter()
    batch = list(rows)
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                affected = cur.executemany(sql, batch) or 0
            conn.commit()
            logger.info("db_many kind=%s batch_size=%s affected=%s duration_ms=%.2f", _sql_kind(sql), len(batch), affected, (time.perf_counter() - started_at) * 1000)
            return affected
        finally:
            conn.close()
    except Exception:
        logger.exception("db_many_failed kind=%s batch_size=%s duration_ms=%.2f", _sql_kind(sql), len(batch), (time.perf_counter() - started_at) * 1000)
        raise


def table_exists(table: str) -> bool:
    """检查表是否存在"""
    rows = execute_query(
        "SELECT COUNT(*) AS cnt FROM information_schema.tables "
        "WHERE table_schema=%s AND table_name=%s",
        (settings.DB_NAME, table),
    )
    return bool(rows and rows[0]["cnt"])


def ping() -> dict:
    """健康检查：数据库连通性 + 表数量"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM information_schema.tables "
                "WHERE table_schema=%s",
                (settings.DB_NAME,),
            )
            cnt = cur.fetchone()["cnt"]
            return {"status": "ok", "tables": cnt}
    finally:
        conn.close()
