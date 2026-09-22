# -*- coding: utf-8 -*-
"""备份 QuantMind MySQL 数据库，并仅保留最近两天的备份文件。"""
from __future__ import annotations

import argparse
import gzip
from datetime import datetime, timedelta
from pathlib import Path
import sys

import pymysql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings


def _sql_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "''")
    return "'" + escaped + "'"


def backup_database(output_dir: str | Path | None = None, retention_days: int = 2) -> dict:
    target = Path(output_dir or (settings.DATA_DIR / "backups")).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = target / f"{settings.DB_NAME}_{stamp}.sql.gz"
    conn = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME,
        charset="utf8mb4", cursorclass=pymysql.cursors.SSCursor,
    )
    try:
        with gzip.open(output, "wt", encoding="utf-8") as handle:
            handle.write("SET FOREIGN_KEY_CHECKS=0;\nSET NAMES utf8mb4;\n")
            with conn.cursor() as cur:
                cur.execute("SHOW TABLES")
                tables = [row[0] for row in cur.fetchall()]
                for table in tables:
                    safe = table.replace("`", "``")
                    with conn.cursor() as ddl:
                        ddl.execute(f"SHOW CREATE TABLE `{safe}`")
                        create_sql = ddl.fetchone()[1]
                    handle.write(f"DROP TABLE IF EXISTS `{safe}`;\n{create_sql};\n")
                    cur.execute(f"SELECT * FROM `{safe}`")
                    for row in cur:
                        values = ",".join(_sql_value(value) for value in row)
                        handle.write(f"INSERT INTO `{safe}` VALUES ({values});\n")
            handle.write("SET FOREIGN_KEY_CHECKS=1;\n")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    finally:
        conn.close()

    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for path in target.glob(f"{settings.DB_NAME}_*.sql.gz"):
        if path != output and datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
            path.unlink()
            removed += 1
    return {"file": str(output), "removed": removed, "retention_days": retention_days}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--retention-days", type=int, default=2)
    args = parser.parse_args()
    print(backup_database(args.output_dir, args.retention_days))
