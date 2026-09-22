# -*- coding: utf-8 -*-
"""启动 QuantMind FastAPI 服务
用法: python run.py  或  uvicorn app.main:app --reload
"""
import uvicorn

from app.config import settings
from app.logging_config import configure_logging

configure_logging(settings.LOG_DIR, settings.LOG_LEVEL)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
    )
