# -*- coding: utf-8 -*-
"""QuantMind 统一日志配置。"""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.request_context import get_request_id


class RequestIdFilter(logging.Filter):
    """为所有日志记录自动补充当前请求 ID。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "cookie", "set-cookie", "access_token", "refresh_token",
}


def redact(value: Any, limit: int = 4000) -> Any:
    """递归脱敏并限制日志字段大小，避免凭据和超大请求体进入日志。"""
    if isinstance(value, dict):
        return {
            str(key): "***REDACTED***" if str(key).lower().replace("-", "_") in SENSITIVE_KEYS
            else redact(item, limit)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, limit) for item in value[:50]]
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:limit]}...<truncated>"
    return value


def format_value(value: Any) -> str:
    try:
        return json.dumps(redact(value), ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return repr(value)


def configure_logging(log_dir: Path, level: str = "INFO") -> None:
    """配置控制台和统一应用文件日志，重复调用安全。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(process)d] request_id=%(request_id)s %(message)s"
    )
    request_filter = RequestIdFilter()
    if not any(getattr(handler, "name", "") == "quantmind-console" for handler in root.handlers):
        console = logging.StreamHandler()
        console.name = "quantmind-console"
        console.setFormatter(formatter)
        console.addFilter(request_filter)
        root.addHandler(console)
    if not any(getattr(handler, "name", "") == "quantmind-app-file" for handler in root.handlers):
        file_handler = RotatingFileHandler(
            log_dir / "app.log", maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.name = "quantmind-app-file"
        file_handler.setFormatter(formatter)
        file_handler.addFilter(request_filter)
        root.addHandler(file_handler)
    for handler in root.handlers:
        if getattr(handler, "name", "") in {"quantmind-console", "quantmind-app-file"}:
            handler.setFormatter(formatter)
            if not any(isinstance(item, RequestIdFilter) for item in handler.filters):
                handler.addFilter(request_filter)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "apscheduler"):
        logging.getLogger(logger_name).setLevel(getattr(logging, level.upper(), logging.INFO))
