#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库备份脚本"""
import os
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# 读取数据库配置
DB_HOST = os.getenv("WUCAI_SQL_HOST", "localhost")
DB_PORT = os.getenv("WUCAI_SQL_PORT", "3309")
DB_USER = os.getenv("WUCAI_SQL_USERNAME", "root")
DB_PASSWORD = os.getenv("WUCAI_SQL_PASSWORD", "root")
DB_NAME = os.getenv("WUCAI_SQL_DB", "wucai_trade")

# 备份目录
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

# 生成备份文件名
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_file = BACKUP_DIR / f"{DB_NAME}_backup_{timestamp}.sql"

print(f"开始备份数据库: {DB_NAME}")
print(f"备份文件: {backup_file}")

# 尝试使用 mysqldump
try:
    cmd = [
        "mysqldump",
        f"-h{DB_HOST}",
        f"-P{DB_PORT}",
        f"-u{DB_USER}",
        f"-p{DB_PASSWORD}",
        "--single-transaction",
        "--routines",
        "--triggers",
        "--events",
        DB_NAME
    ]

    with open(backup_file, "w", encoding="utf-8") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)

    if result.returncode == 0:
        file_size = backup_file.stat().st_size / (1024 * 1024)  # MB
        print(f"✓ 备份成功！文件大小: {file_size:.2f} MB")
        print(f"✓ 备份位置: {backup_file}")
    else:
        print(f"✗ 备份失败: {result.stderr}")
        backup_file.unlink(missing_ok=True)

except FileNotFoundError:
    print("✗ 错误: 未找到 mysqldump 命令")
    print("尝试使用 Python 方式备份...")
    backup_file.unlink(missing_ok=True)

    # 使用 Python pymysql 备份
    try:
        import pymysql

        conn = pymysql.connect(
            host=DB_HOST,
            port=int(DB_PORT),
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset='utf8mb4'
        )

        with open(backup_file, "w", encoding="utf-8") as f:
            cursor = conn.cursor()

            # 写入备份头
            f.write(f"-- MySQL 数据库备份\n")
            f.write(f"-- 数据库: {DB_NAME}\n")
            f.write(f"-- 时间: {datetime.now()}\n")
            f.write(f"-- ----------------------------------------\n\n")
            f.write("SET FOREIGN_KEY_CHECKS=0;\n\n")

            # 获取所有表
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]

            for table in tables:
                print(f"  备份表: {table}")

                # 获取建表语句
                cursor.execute(f"SHOW CREATE TABLE `{table}`")
                create_table = cursor.fetchone()[1]
                f.write(f"-- 表结构: {table}\n")
                f.write(f"DROP TABLE IF EXISTS `{table}`;\n")
                f.write(f"{create_table};\n\n")

                # 获取数据
                cursor.execute(f"SELECT * FROM `{table}`")
                rows = cursor.fetchall()

                if rows:
                    # 获取列信息
                    cursor.execute(f"DESCRIBE `{table}`")
                    columns = [col[0] for col in cursor.fetchall()]

                    f.write(f"-- 数据: {table} ({len(rows)} 行)\n")
                    f.write(f"INSERT INTO `{table}` (`{'`, `'.join(columns)}`) VALUES\n")

                    for i, row in enumerate(rows):
                        values = []
                        for val in row:
                            if val is None:
                                values.append("NULL")
                            elif isinstance(val, (int, float)):
                                values.append(str(val))
                            else:
                                # 转义字符串
                                val_str = str(val).replace("\\", "\\\\").replace("'", "\\'")
                                values.append(f"'{val_str}'")

                        if i < len(rows) - 1:
                            f.write(f"  ({', '.join(values)}),\n")
                        else:
                            f.write(f"  ({', '.join(values)});\n")

                    f.write("\n")

            f.write("SET FOREIGN_KEY_CHECKS=1;\n")

            cursor.close()
            conn.close()

        file_size = backup_file.stat().st_size / (1024 * 1024)  # MB
        print(f"✓ 备份成功！文件大小: {file_size:.2f} MB")
        print(f"✓ 备份位置: {backup_file}")

    except Exception as e:
        print(f"✗ Python 备份失败: {e}")
        backup_file.unlink(missing_ok=True)

except Exception as e:
    print(f"✗ 备份过程出错: {e}")
    backup_file.unlink(missing_ok=True)
