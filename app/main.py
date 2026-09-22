# -*- coding: utf-8 -*-
"""QuantMind FastAPI 应用入口"""
from contextlib import asynccontextmanager
import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app import scheduler
from app.logging_config import configure_logging, format_value
from app.request_context import reset_request_id, set_request_id
from app.api import backtest, chat, dashboard, diagnoses, fundamental, market, morning, opportunities, parameters, polymarket, qlib, qlib_research, risk_control, risk_plans, sector_opportunities, sentiment, sentiment_reports, sentiment_watchlist, signals, stocks, sync, technical
from app.config import settings
from app.database import ping
from app.services.sector_opportunity import init_sector_opportunity_schema
from app.services.qlib_research import init_qlib_research_schema
from app.services.qlib_data_sync import init_qlib_data_sync_schema
from app.services.qlib_time_split import init_qlib_time_split_schema
from app.services.stock_diagnosis import init_stock_diagnosis_schema
from app.services.diagnosis_news_policy import build_news_policy_snapshot
from app.services.diagnosis_research_report import init_schema as init_diagnosis_research_report_schema
from app.services.diagnosis_events import init_schema as init_diagnosis_events_schema
from app.services.diagnosis_scheduling import init_schema as init_diagnosis_scheduling_schema
from app.services.diagnosis_watchlist import init_schema as init_diagnosis_watchlist_schema
from app.services.sentiment_research_report import init_schema as init_sentiment_research_report_schema
from app.services.sentiment_watchlist import init_schema as init_sentiment_watchlist_schema
from app.services.polymarket_sync import init_schema as init_polymarket_signal_schema
from app.signals import init_chan_signal_schema
from app.trade_plans import init_trade_plan_schema
from app.services.risk_control import init_risk_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化业务表并加载定时任务调度器；关闭时安全释放"""
    logger.info("application_starting scheduler_enabled=%s", settings.SCHEDULER_ENABLED)
    init_trade_plan_schema()
    init_risk_schema()
    init_chan_signal_schema()
    init_sector_opportunity_schema()
    init_qlib_time_split_schema()
    init_qlib_research_schema()
    init_qlib_data_sync_schema()
    init_stock_diagnosis_schema()
    init_diagnosis_research_report_schema()
    init_diagnosis_events_schema()
    init_diagnosis_watchlist_schema()
    init_diagnosis_scheduling_schema()
    init_sentiment_research_report_schema()
    init_sentiment_watchlist_schema()
    init_polymarket_signal_schema()
    if settings.SCHEDULER_ENABLED:
        scheduler.start_scheduler()
    logger.info("application_started api_prefix=%s", settings.API_PREFIX)
    try:
        yield
    finally:
        scheduler.shutdown_scheduler()
        logger.info("application_stopped")


configure_logging(settings.LOG_DIR, settings.LOG_LEVEL)
logger = logging.getLogger("quantmind.http")


def _request_id_from_header(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate or len(candidate) > 128 or any(ord(char) < 32 for char in candidate):
        return str(uuid.uuid4())
    return candidate


app = FastAPI(
    title="QuantMind 量化交易系统",
    description=(
        "基于 MySQL（wucai_trade）的量化交易数据访问与同步服务。\n\n"
        "**接口分组**：\n"
        "- **股票数据**：日K线、财务、新闻、研报一致预期、公告及 RAG 语义检索\n"
        "- **市场数据**：宏观指标、国债收益率、财经日历、板块行情\n"
        "- **市场情绪**：情绪聚合、新闻情绪明细、恐慌/贪婪指数、市场事件\n"
        "- **数据同步**：各数据源的同步触发、定时任务管理与执行日志\n\n"
        "**常用入口**：\n"
        "- Swagger 文档：`/docs` ｜ ReDoc 文档：`/redoc`\n"
        "- 健康检查：`GET /health`"
    ),
    version="1.1.0",
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = _request_id_from_header(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    context_token = set_request_id(request_id)
    started_at = time.perf_counter()
    body = await request.body()
    request_body = "<empty>"
    if body and request.method not in {"GET", "HEAD"}:
        try:
            request_body = format_value(json.loads(body))
        except (UnicodeDecodeError, json.JSONDecodeError):
            request_body = f"<binary:{len(body)} bytes>"
    try:
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "http_request_failed method=%s path=%s query=%s body=%s duration_ms=%.2f",
                request.method, request.url.path, format_value(dict(request.query_params)), request_body,
                (time.perf_counter() - started_at) * 1000,
            )
            raise
        duration_ms = (time.perf_counter() - started_at) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "http_request method=%s path=%s query=%s status=%s duration_ms=%.2f body=%s",
            request.method, request.url.path, format_value(dict(request.query_params)),
            response.status_code, duration_ms, request_body,
        )
        return response
    finally:
        reset_request_id(context_token)


# CORS（允许前端原型跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(stocks.router, prefix=settings.API_PREFIX)
app.include_router(chat.router, prefix=settings.API_PREFIX)
app.include_router(diagnoses.router, prefix=settings.API_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_PREFIX)
app.include_router(opportunities.router, prefix=settings.API_PREFIX)
app.include_router(sector_opportunities.router, prefix=settings.API_PREFIX)
app.include_router(backtest.router, prefix=settings.API_PREFIX)
app.include_router(risk_plans.router, prefix=settings.API_PREFIX)
app.include_router(risk_control.router, prefix=settings.API_PREFIX)
app.include_router(market.router, prefix=settings.API_PREFIX)
app.include_router(morning.router, prefix=settings.API_PREFIX)
app.include_router(sentiment.router, prefix=settings.API_PREFIX)
app.include_router(sentiment_reports.router, prefix=settings.API_PREFIX)
app.include_router(sentiment_watchlist.router, prefix=settings.API_PREFIX)
app.include_router(polymarket.router, prefix=settings.API_PREFIX)
app.include_router(fundamental.router, prefix=settings.API_PREFIX)
app.include_router(signals.router, prefix=settings.API_PREFIX)
app.include_router(sync.router, prefix=settings.API_PREFIX)
app.include_router(parameters.router)
app.include_router(qlib.router, prefix=settings.API_PREFIX)
app.include_router(qlib_research.router, prefix=settings.API_PREFIX)
app.include_router(technical.router, prefix=settings.API_PREFIX)


@app.get("/", summary="服务信息概览", description="返回服务名称、文档地址、API 前缀与数据库名称。")
def root():
    return {
        "name": "QuantMind 量化交易系统",
        "docs": "/docs",
        "api": settings.API_PREFIX,
        "database": settings.DB_NAME,
    }


@app.get("/health", summary="健康检查", description="检查服务与数据库连接是否正常。数据库正常时返回 status=ok，异常时返回错误信息。")
def health():
    try:
        info = ping()
        return {"status": "ok", "database": info}
    except Exception as e:  # noqa: BLE001
        logger.exception("health_check_failed")
        return {"status": "error", "database": str(e)}
