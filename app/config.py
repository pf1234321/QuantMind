# -*- coding: utf-8 -*-
"""QuantMind 全局配置：从 .env 读取数据库与服务参数"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（app 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    """统一配置对象"""

    # ---------- 本地数据路径 ----------
    DATA_DIR: Path = BASE_DIR / "data"
    SIGNAL_STORE_PATH: Path = Path(os.getenv("SIGNAL_STORE_PATH", str(DATA_DIR / "strategy_signals.jsonl"))).expanduser().resolve()
    REBUILD_DIR: Path = DATA_DIR / "chanpy_rebuilds"

    # ---------- MySQL ----------
    DB_HOST: str = os.getenv("WUCAI_SQL_HOST", "localhost")
    DB_PORT: int = int(os.getenv("WUCAI_SQL_PORT", "3309"))
    DB_USER: str = os.getenv("WUCAI_SQL_USERNAME", "root")
    DB_PASSWORD: str = os.getenv("WUCAI_SQL_PASSWORD", "root")
    DB_NAME: str = os.getenv("WUCAI_SQL_DB", "wucai_trade")

    # ---------- FastAPI ----------
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_PREFIX: str = "/api/v1"

    # ---------- 日志 ----------
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: Path = Path(os.getenv("LOG_DIR", str(DATA_DIR / "logs"))).expanduser().resolve()

    # ---------- K线同步 ----------
    EASTMONEY_COOKIE: str = os.getenv("EASTMONEY_COOKIE", "").strip()
    EASTMONEY_PAGE_URL: str = os.getenv(
        "EASTMONEY_PAGE_URL",
        "https://quote.eastmoney.com/",
    )
    EASTMONEY_KLINE_URL: str = os.getenv(
        "EASTMONEY_KLINE_URL",
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
    )
    KLINE_REQUEST_TIMEOUT: int = int(os.getenv("KLINE_REQUEST_TIMEOUT", "20"))
    KLINE_DATA_START: str = os.getenv("KLINE_DATA_START", "20230101")
    KLINE_MAX_ATTEMPTS: int = int(os.getenv("KLINE_MAX_ATTEMPTS", "3"))
    SW_INIT_START_DATE: str = os.getenv("SW_INIT_START_DATE", "20240101")
    SW_DOWNLOAD_BATCH: int = int(os.getenv("SW_DOWNLOAD_BATCH", "200"))
    SW_MAX_WORKERS: int = int(os.getenv("SW_MAX_WORKERS", "5"))

    # ---------- 定时任务 ----------
    SCHEDULER_ENABLED: bool = os.getenv("SCHEDULER_ENABLED", "true").lower() in ("true", "1", "yes")

    # ---------- 公告 RAG（DashScope 通义千问） ----------
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen-plus")
    VECTOR_DB_DIR: Path = BASE_DIR / "data" / "vector_db"
    PDF_DIR: Path = BASE_DIR / "data" / "pdfs"

    @property
    def db_uri(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )


settings = Settings()
