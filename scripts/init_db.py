# -*- coding: utf-8 -*-
"""初始化数据库：执行 app/sql/schema.sql 建表（幂等）
用法: python scripts/init_db.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql

from app.config import settings

# 去掉 SQL 中的注释行，避免干扰语句解析
_SQL_COMMENT_LINE = re.compile(r"^\s*--.*$", re.MULTILINE)


def init_db() -> list[str]:
    schema_path = Path(__file__).resolve().parent.parent / "app" / "sql" / "schema.sql"
    raw = schema_path.read_text(encoding="utf-8")
    sql = _SQL_COMMENT_LINE.sub("", raw)

    conn = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT,
        user=settings.DB_USER, password=settings.DB_PASSWORD,
        database=settings.DB_NAME, charset="utf8mb4",
    )
    created: list[str] = []
    try:
        with conn.cursor() as cur:
            statements = [s.strip() for s in sql.split(";") if s.strip()]
            for stmt in statements:
                if not stmt:
                    continue
                add_column = re.search(
                    r"ALTER TABLE [`]?([\w]+)[`]? ADD COLUMN [`]?([\w]+)[`]?",
                    stmt,
                    re.IGNORECASE,
                )
                table_match = re.search(
                    r"(?:ALTER TABLE|CREATE TABLE IF NOT EXISTS) [`]?([\w]+)[`]?",
                    stmt,
                    re.IGNORECASE,
                )
                if table_match:
                    table = table_match.group(1)
                    cur.execute(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema=%s AND table_name=%s",
                        (settings.DB_NAME, table),
                    )
                    table_exists = bool(cur.fetchone()[0])
                    if stmt.upper().startswith("ALTER TABLE") and not table_exists:
                        continue
                if add_column:
                    table, column = add_column.groups()
                    cur.execute(
                        "SELECT COUNT(*) AS cnt FROM information_schema.columns "
                        "WHERE table_schema=%s AND table_name=%s AND column_name=%s",
                        (settings.DB_NAME, table, column),
                    )
                    if cur.fetchone()[0]:
                        continue
                cur.execute(stmt)
                m = re.search(r"CREATE TABLE IF NOT EXISTS `(\w+)`", stmt)
                if m:
                    created.append(m.group(1))
        conn.commit()
    finally:
        conn.close()
    return created


if __name__ == "__main__":
    tables = init_db()
    print(f"✅ 建表完成，共处理 {len(tables)} 张表:")
    for t in tables:
        print(f"   - {t}")
