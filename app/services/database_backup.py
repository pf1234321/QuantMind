# -*- coding: utf-8 -*-
"""数据库备份服务，供调度器和命令行脚本共用。"""
from scripts.backup_database import backup_database

__all__ = ["backup_database"]
