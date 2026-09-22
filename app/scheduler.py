# -*- coding: utf-8 -*-
"""数据同步定时调度器（APScheduler）

- 通过 cron 表达式定时触发各同步任务（默认交易日收盘后增量同步）
- 每次执行统一记录到 sync_task_log（触发方式标记为 scheduler）
- 提供 run_task() 供 API 手动触发（trigger=manual/api），同样写日志

启用方式：.env 中 SCHEDULER_ENABLED=true（默认开启）；FastAPI 启动时自动 start。
"""
import logging
import traceback
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.logging_config import configure_logging, format_value

configure_logging(settings.LOG_DIR, settings.LOG_LEVEL)

from app.services import (
    announcement_pdf,
    announcement_sync,
    calendar_sync,
    database_backup,
    catalyst_sync,
    industry_sync,
    kline_sync,
    macro_sync,
    news_sync,
    polymarket_sync,
    report_sync,
    sector_opportunity,
    sector_sync,
    sentiment_research_report,
    sentiment_sync,
    task_log_service,
)

logger = logging.getLogger(__name__)


def _default_stocks(limit: int = 200) -> list[tuple[str, str]]:
    """默认从 trade_stock_status 取前 N 只股票作为同步标的"""
    from app.database import execute_query

    rows = execute_query(
        "SELECT stock_code, stock_name FROM trade_stock_status "
        "WHERE stock_name IS NOT NULL LIMIT %s",
        (limit,),
    )
    return [(r["stock_code"].split(".")[0], r["stock_name"]) for r in rows]


def _parse_stock_codes(stock_codes: str | list | None) -> list[tuple[str, str]] | None:
    """解析股票代码参数，返回 [(code, name), ...] 格式

    支持格式：
    - 字符串：逗号、空格或换行分隔的代码列表，如 "600519,000858"
    - 列表：已经是列表格式
    - None：返回 None
    """
    if stock_codes is None:
        return None

    from app.database import execute_query
    import re

    # 如果已经是正确格式的列表，直接返回
    if isinstance(stock_codes, list):
        if stock_codes and isinstance(stock_codes[0], tuple) and len(stock_codes[0]) == 2:
            return stock_codes
        # 如果是纯代码列表，需要查询名称
        codes = stock_codes
    else:
        # 字符串格式，按分隔符拆分
        codes = [c.strip() for c in re.split(r'[,\s\n]+', str(stock_codes)) if c.strip()]

    if not codes:
        return None

    # 批量查询股票名称
    placeholders = ','.join(['%s'] * len(codes))
    rows = execute_query(
        f"SELECT stock_code, stock_name FROM trade_stock_status "
        f"WHERE stock_code IN ({placeholders}) OR SUBSTRING_INDEX(stock_code, '.', 1) IN ({placeholders})",
        codes + codes
    )

    # 构建代码到名称的映射
    code_map = {}
    for row in rows:
        pure_code = row['stock_code'].split('.')[0]
        code_map[pure_code] = row['stock_name']
        code_map[row['stock_code']] = row['stock_name']

    # 返回结果，未找到名称的使用代码本身
    result = []
    for code in codes:
        pure_code = code.split('.')[0]
        name = code_map.get(code) or code_map.get(pure_code) or code
        result.append((pure_code, name))

    return result if result else None


def _financial_task(**kwargs):
    """财务同步：akshare 跨平台（东财业绩报表，macOS/Windows/Linux 均可用）"""
    from app.services.financial_sync import sync_financial

    return sync_financial(
        stock_codes=kwargs.get("stock_codes"),
        quarters=kwargs.get("quarters", 2),
        enrich_detail=kwargs.get("enrich_detail", False),
        test_mode=kwargs.get("test_mode", False),
    )


def _technical_indicators_task(**kwargs):
    """技术指标计算：支持日线/周线/月线"""
    from app.services.technical_indicators import sync_technical_indicators

    period = kwargs.get("period", "daily")
    stock_codes = kwargs.get("stock_codes")

    return sync_technical_indicators(
        stock_codes=stock_codes,
        start_date=kwargs.get("start_date"),
        end_date=kwargs.get("end_date"),
        period=period,
        force_refresh=kwargs.get("force_refresh", False),
    )


def _technical_patterns_task(**kwargs):
    """技术形态识别"""
    from app.services.technical_patterns import sync_pattern_detection

    return sync_pattern_detection(
        stock_codes=kwargs.get("stock_codes"),
        lookback_days=kwargs.get("lookback_days", 120),
        period=kwargs.get("period", "daily"),
    )


def _quarterly_parameter_task(**kwargs):
    from app.backtest.data import load_daily_bars
    from app.backtest.parameters import ParameterState
    from app.backtest.quarterly import QuarterlyParameterService
    from app.backtest.quarterly_repository import QuarterlyRepository
    from app.database import execute_query
    from app.strategy.atr_chan import build_internal_adapter
    from datetime import date

    as_of = kwargs.get("data_as_of") or str(date.today())
    quarter = kwargs.get("evaluation_quarter") or f"{date.today().year}-Q{((date.today().month - 1) // 3) + 1}"
    repository = QuarterlyRepository()
    current_row = repository.current()
    current = ParameterState(
        atr_period=int((current_row or {}).get("atr_period", 14)),
        atr_exit_mult=float((current_row or {}).get("atr_exit_mult", 2.5)),
        parameter_version=(current_row or {}).get("parameter_version", "initial"),
        effective_date=str((current_row or {}).get("effective_date") or "") or None,
    )
    stocks = [row["stock_code"] for row in execute_query("SELECT DISTINCT stock_code FROM trade_stock_status WHERE stock_code IS NOT NULL ORDER BY stock_code")]
    data = {}
    skipped_stocks = []
    for code in stocks:
        try:
            data[code] = load_daily_bars(code, kwargs.get("start_date", "2022-01-01"), as_of, execute_query)
        except ValueError as exc:
            if str(exc) == "行情数据为空":
                skipped_stocks.append({"stock_code": code, "reason": str(exc)})
                continue
            raise
    if not data:
        return {"status": "blocked", "reason": "data_incomplete", "missing": "all_stock_daily_bars", "stock_count": len(stocks), "skipped_stocks": skipped_stocks}
    result = QuarterlyParameterService(repository=repository, output_dir=kwargs.get("output_dir", "data/backtest/quarterly")).run(
        data_by_stock=data, stock_codes=list(data), current=current, evaluation_quarter=quarter,
        data_as_of=as_of, candidates=kwargs.get("candidates"), range_start=kwargs.get("range_start"),
        range_end=kwargs.get("range_end"), step=kwargs.get("step"), baseline=bool(kwargs.get("baseline", False)),
        adapter=build_internal_adapter(),
    )
    if skipped_stocks and isinstance(result, dict):
        result["skipped_stocks"] = skipped_stocks
        result["stock_count"] = len(stocks)
        result["valid_stock_count"] = len(data)
    return result


# ------------------------------------------------------------
# 任务注册表
# cron 使用标准 5 段表达式: 分 时 日 月 周
#   - day 周 用 1-5 表示周一~周五（交易日）
#   - 默认时间按 A 股收盘(15:00)后错峰编排
#   - func 统一接受 **kwargs，定时触发无参；API 手动触发可传参
# ------------------------------------------------------------
TASKS: dict[str, dict] = {
    "industry": {
        "description": "申万行业分类+股本（低频，每周一 06:30）",
        "func": lambda **kw: industry_sync.sync_industry(
            fetch_shares=kw.get("fetch_shares", False)
        ),
        "cron": "30 6 * * 1",
        "enabled": True,
    },
    "kline": {
        "description": "K线日线（交易日 16:30，baostock 源）",
        "func": lambda **kw: kline_sync.sync_kline(
            stock_codes=kw.get("stock_codes"),
            start_date=kw.get("start_date"),
            end_date=kw.get("end_date"),
            force_refresh=kw.get("force_refresh", False),
        ),
        "cron": "30 16 * * 1-5",
        "enabled": True,
    },
    "sectors": {
        "description": "板块等权合成指数（交易日 17:30，依赖K线）",
        "func": lambda **kw: sector_sync.rebuild_all_sectors(
            level=kw.get("level", 2),
            days=kw.get("days", 30),
            full=kw.get("full", False),
        ),
        "cron": "30 17 * * 1-5",
        "enabled": True,
    },
    "sector_opportunities": {
        "description": "板块选股机会扫描（交易日 17:45，依赖完整板块和前复权K线）",
        "func": lambda **kw: _sector_opportunity_task(**kw),
        "cron": "45 17 * * 1-5",
        "enabled": True,
    },
    "news": {
        "description": "个股新闻（每日 18:00）",
        "func": lambda **kw: news_sync.sync_news(
            stock_codes=_parse_stock_codes(kw.get("stock_codes")) or _default_stocks(kw.get("limit", 200)),
            limit_per_stock=kw.get("limit_per_stock", 50),
        ),
        "cron": "0 18 * * *",
        "enabled": True,
    },
    "report": {
        "description": "研报一致预期（每日 18:30）",
        "func": lambda **kw: report_sync.sync_report(
            kw.get("stock_codes") or _default_stocks(kw.get("limit", 200))
        ),
        "cron": "30 18 * * *",
        "enabled": True,
    },
    "macro": {
        "description": "宏观+利率宽表（每日 19:00）",
        "func": lambda **kw: macro_sync.sync_macro(),
        "cron": "0 19 * * *",
        "enabled": True,
    },
    "calendar": {
        "description": "财经日历（每日 06:30）",
        "func": lambda **kw: calendar_sync.sync_calendar(
            kw.get("start_date"), kw.get("end_date")
        ),
        "cron": "30 6 * * *",
        "enabled": True,
    },
    "catalyst": {
        "description": "AI催化剂（每日 20:00，需 DASHSCOPE_API_KEY）",
        "func": lambda **kw: catalyst_sync.sync_catalyst(),
        "cron": "0 20 * * *",
        "enabled": True,
    },
    "sentiment": {
        "description": "新闻情感分析+情绪聚合（每日 19:30，依赖 news 数据；无 DASHSCOPE_API_KEY 时规则降级）",
        "func": lambda **kw: sentiment_sync.sync_sentiment_detail(
            days=kw.get("days", 7),
            limit=kw.get("limit", 200),
        ) | sentiment_sync.sync_sentiment_aggregate(days=kw.get("days", 7)),
        "cron": "30 19 * * 1-5",
        "enabled": True,
    },
    "events": {
        "description": "市场事件识别（每日 21:00，依赖 sentiment 数据）",
        "func": lambda **kw: sentiment_sync.sync_market_events(
            days=kw.get("days", 7),
        ),
        "cron": "0 21 * * 1-5",
        "enabled": True,
    },
    "fear_index": {
        "description": "市场恐慌/贪婪指数（每日 21:30，VIX+情绪聚合综合）",
        "func": lambda **kw: sentiment_sync.sync_fear_index(
            days=kw.get("days", 3),
        ),
        "cron": "30 21 * * 1-5",
        "enabled": True,
    },
    "financial": {
        "description": "财务数据（akshare 跨平台，每日 20:30）",
        "func": lambda **kw: _financial_task(**kw),
        "cron": "30 20 * * *",
        "enabled": True,
    },
    "atr_quarterly_parameter": {
        "description": "ATR 季度参数验证（季度首周工作日）",
        "func": _quarterly_parameter_task,
        "cron": "0 10 1-7 1,4,7,10 1-5",
        "enabled": True,
    },
    "announcement": {
        "description": "东财全市场公告增量（每日 22:00，回看 3 天）",
        "func": lambda **kw: announcement_sync.sync_announcement_daily(
            start_date=kw.get("start_date"),
            end_date=kw.get("end_date"),
            lookback_days=kw.get("lookback_days", 3),
        ),
        "cron": "0 22 * * *",
        "enabled": True,
    },
    "ann_track": {
        "description": "巨潮cninfo股票池公告追踪（每日 22:30，默认前 100 只全量+本地打标）",
        "func": lambda **kw: announcement_sync.track_stock_announcements(
            stock_codes=kw.get("stock_codes") or [
                c for c, _ in _default_stocks(kw.get("limit", 100))
            ],
            lookback_days=kw.get("lookback_days", 7),
            categories=kw.get("categories") or [],
            only_important=kw.get("only_important", False),
        ),
        "cron": "30 22 * * 1-5",
        "enabled": True,
    },
    "database_backup": {
        "description": "数据库备份（每日 02:00，保留最近2天）",
        "func": lambda **kw: database_backup.backup_database(retention_days=2),
        "cron": "0 2 * * *",
        "enabled": True,
    },
    "pdf_sync": {
        "description": "公告PDF→Chroma向量库（每日 22:35，紧跟公告同步，回看3天）",
        "func": lambda **kw: announcement_pdf.sync_announcement_pdfs(
            lookback_days=kw.get("lookback_days", 3),
            limit=kw.get("limit", 200),
            only_important=kw.get("only_important", False),
            reindex=kw.get("reindex", False),
        ),
        "cron": "35 22 * * *",
        "enabled": True,
    },
    "polymarket": {
        "description": "Polymarket 预测市场信号（每日 23:00，外部 API 国内可能不可达）",
        "func": lambda **kw: polymarket_sync.sync_polymarket(
            keywords=kw.get("keywords"),
            min_volume=kw.get("min_volume", 10000),
            top_n=kw.get("top_n", 20),
        ),
        "cron": "0 23 * * 1-5",
        "enabled": True,
    },
    "sentiment_report": {
        "description": "舆情报告兜底生成（每日 23:30，从监控列表批量跑）",
        "func": lambda **kw: sentiment_research_report.batch_generate_reports(
            group=kw.get("group", "default"),
            limit=kw.get("limit", 20),
            days=kw.get("days", 7),
        ),
        "cron": "30 23 * * 1-5",
        "enabled": False,
    },
    "technical_indicators": {
        "description": "技术指标计算（交易日 18:15，K线同步后计算）",
        "func": lambda **kw: _technical_indicators_task(**kw),
        "cron": "15 18 * * 1-5",
        "enabled": True,
    },
    "technical_patterns": {
        "description": "技术形态识别（交易日 18:45，指标计算后识别）",
        "func": lambda **kw: _technical_patterns_task(**kw),
        "cron": "45 18 * * 1-5",
        "enabled": True,
    },
}


TASK_PARAMETERS: dict[str, list[dict]] = {
    "industry": [{"name": "fetch_shares", "label": "同步股本", "type": "boolean", "default": False}],
    "kline": [
        {"name": "stock_codes", "label": "股票代码", "type": "string_list", "required": False, "description": "可选，多个代码用逗号、空格或换行分隔"},
        {"name": "start_date", "label": "起始日期", "type": "string", "description": "可选，格式 YYYY-MM-DD"},
        {"name": "end_date", "label": "结束日期", "type": "string", "description": "可选，格式 YYYY-MM-DD"},
        {"name": "force_refresh", "label": "强制刷新", "type": "boolean", "default": False},
    ],
    "sectors": [{"name": "level", "label": "板块级别", "type": "integer", "default": 2, "min": 1, "max": 2}, {"name": "days", "label": "回算天数", "type": "integer", "default": 30, "min": 1}, {"name": "full", "label": "全量重算", "type": "boolean", "default": False}],
    "news": [
        {"name": "stock_codes", "label": "股票代码", "type": "string_list", "required": False, "description": "可选，多个代码用逗号、空格或换行分隔；不传则使用默认股票池"},
        {"name": "limit", "label": "股票数量上限", "type": "integer", "default": 100, "min": 1, "max": 5000, "description": "stock_codes 未指定时，从默认股票池取前 N 只"},
        {"name": "limit_per_stock", "label": "每只股票新闻数", "type": "integer", "default": 50, "min": 1, "max": 200, "description": "每只股票最多获取的新闻条数"}
    ],
    "report": [{"name": "limit", "label": "股票数量上限", "type": "integer", "default": 100, "min": 1, "max": 5000}],
    "calendar": [{"name": "start_date", "label": "起始日期", "type": "string", "description": "可选，格式 YYYYMMDD"}, {"name": "end_date", "label": "结束日期", "type": "string", "description": "可选，格式 YYYYMMDD"}],
    "sentiment": [{"name": "days", "label": "分析天数", "type": "integer", "default": 7, "min": 1, "max": 30}, {"name": "limit", "label": "新闻条数上限", "type": "integer", "default": 200, "min": 1, "max": 2000}],
    "events": [{"name": "days", "label": "分析天数", "type": "integer", "default": 7, "min": 1, "max": 30}],
    "fear_index": [{"name": "days", "label": "计算天数", "type": "integer", "default": 3, "min": 1, "max": 30}],
    "financial": [
        {"name": "stock_codes", "label": "股票代码", "type": "string_list", "description": "可选；不传则同步 AkShare 返回的全部股票"},
        {"name": "quarters", "label": "报告期数量", "type": "integer", "default": 2, "min": 1, "max": 12},
        {"name": "enrich_detail", "label": "补全财务明细", "type": "boolean", "default": False},
        {"name": "test_mode", "label": "测试模式", "type": "boolean", "default": False},
    ],
    "announcement": [{"name": "start_date", "label": "起始日期", "type": "string", "description": "可选，格式 YYYYMMDD"}, {"name": "end_date", "label": "结束日期", "type": "string", "description": "可选，格式 YYYYMMDD"}, {"name": "lookback_days", "label": "回看天数", "type": "integer", "default": 3, "min": 1, "max": 30}],
    "ann_track": [{"name": "stock_codes", "label": "股票代码", "type": "string_list", "description": "可选，默认股票池前100只"}, {"name": "lookback_days", "label": "回看天数", "type": "integer", "default": 7, "min": 1, "max": 60}, {"name": "only_important", "label": "仅重要公告", "type": "boolean", "default": False}, {"name": "categories", "label": "公告分类", "type": "string_list", "description": "可选"}],
    "pdf_sync": [{"name": "lookback_days", "label": "回看天数", "type": "integer", "default": 3, "min": 1}, {"name": "limit", "label": "处理条数上限", "type": "integer", "default": 200, "min": 1}, {"name": "only_important", "label": "仅重要公告", "type": "boolean", "default": False}, {"name": "reindex", "label": "重建索引", "type": "boolean", "default": False}],
    "atr_quarterly_parameter": [{"name": "data_as_of", "label": "数据截止日期", "type": "string", "description": "可选，格式 YYYY-MM-DD"}, {"name": "evaluation_quarter", "label": "评估季度", "type": "string", "description": "可选，例如 2026-Q3"}],
    "polymarket": [
        {"name": "keywords", "label": "搜索关键词", "type": "string_list", "description": "留空使用默认关键词列表"},
        {"name": "min_volume", "label": "最小交易量(USD)", "type": "integer", "default": 10000, "min": 0},
        {"name": "top_n", "label": "Top N", "type": "integer", "default": 20, "min": 1, "max": 100},
    ],
    "sentiment_report": [
        {"name": "group", "label": "监控分组", "type": "string", "default": "default"},
        {"name": "limit", "label": "监控股票上限", "type": "integer", "default": 20, "min": 1, "max": 200},
        {"name": "days", "label": "回看天数", "type": "integer", "default": 7, "min": 1, "max": 30},
    ],
    "technical_indicators": [
        {"name": "stock_codes", "label": "股票代码", "type": "string_list", "required": False, "description": "可选，多个代码用逗号、空格或换行分隔；不传则计算全部股票"},
        {"name": "period", "label": "周期", "type": "string", "default": "daily", "description": "daily/weekly/monthly"},
        {"name": "start_date", "label": "起始日期", "type": "string", "description": "可选，格式 YYYY-MM-DD"},
        {"name": "end_date", "label": "结束日期", "type": "string", "description": "可选，格式 YYYY-MM-DD"},
        {"name": "force_refresh", "label": "强制重算", "type": "boolean", "default": False},
    ],
    "technical_patterns": [
        {"name": "stock_codes", "label": "股票代码", "type": "string_list", "required": False, "description": "可选，多个代码用逗号、空格或换行分隔；不传则识别全部股票"},
        {"name": "period", "label": "周期", "type": "string", "default": "daily", "description": "daily/weekly/monthly"},
        {"name": "lookback_days", "label": "回看天数", "type": "integer", "default": 120, "min": 30, "max": 365},
    ],
}

_scheduler: Optional[BackgroundScheduler] = None


def _sector_opportunity_task(**kwargs):
    return sector_opportunity.scan_sector_opportunities(
        level=kwargs.get("level", 2),
        end_date=kwargs.get("end_date"),
        top_n=kwargs.get("top_n", 5),
        top_sector_n=kwargs.get("top_sector_n", 10),
    )


def _cron_trigger(expr: str) -> CronTrigger:
    """解析 '分 时 日 月 周' 5 段 cron 表达式为 CronTrigger"""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"非法 cron 表达式: {expr}")
    minute, hour, day, month, dow = parts
    return CronTrigger(
        minute=minute, hour=hour, day=day, month=month, day_of_week=dow
    )


def run_task(task_name: str, trigger: str = "manual", **kwargs) -> dict:
    """统一执行入口：写日志 -> 调用同步函数 -> 更新日志。

    trigger: scheduler / manual / api
    返回 {task, log_id, status, result}
    """
    task = TASKS.get(task_name)
    if task is None:
        raise KeyError(f"未知任务: {task_name}，可用任务: {list(TASKS.keys())}")
    if not task.get("enabled", True):
        # 禁用任务仍允许手动触发（便于排障）
        pass

    log_id = task_log_service.start_log(task_name, trigger)
    started_at = datetime.now()
    logger.info(
        "task_started task_name=%s log_id=%s trigger=%s parameters=%s",
        task_name, log_id, trigger, format_value(kwargs),
    )
    result = None
    error = None
    try:
        result = task["func"](**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.exception("task_failed task_name=%s log_id=%s trigger=%s", task_name, log_id, trigger)
        error = traceback.format_exc()

    # 无论成功失败，先落库
    status = "success" if error is None else "failed"
    duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
    task_log_service.finish_log(
        log_id,
        status,
        message=task_log_service.to_message(result) if result is not None else error,
        rows_affected=task_log_service._extract_rows_affected(result),
        error=error,
        started_at=started_at,
    )
    logger.info(
        "task_finished task_name=%s log_id=%s trigger=%s status=%s duration_ms=%s rows_affected=%s result=%s",
        task_name, log_id, trigger, status, duration_ms,
        task_log_service._extract_rows_affected(result), format_value(result),
    )
    # 手动触发时让调用方感知失败；定时任务则吞掉异常避免调度器崩溃
    if error is not None and trigger in ("manual", "api"):
        raise RuntimeError(f"[{task_name}] 同步失败: {error[:500]}")
    return {
        "task": task_name,
        "log_id": log_id,
        "status": status,
        "result": result,
    }


def run_all(trigger: str = "manual") -> dict:
    """顺序执行全部启用的任务（含失败容忍）"""
    results = {}
    for name in TASKS:
        if not TASKS[name].get("enabled", True):
            results[name] = {"skipped": True, "reason": "disabled"}
            continue
        try:
            out = run_task(name, trigger=trigger)
            results[name] = {"status": out["status"], "log_id": out["log_id"]}
        except Exception as exc:  # noqa: BLE001
            results[name] = {"status": "failed", "error": str(exc)}
    return results


def start_scheduler() -> BackgroundScheduler:
    """启动后台调度器（幂等）"""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    for name, task in TASKS.items():
        if not task.get("enabled", True):
            logger.info("[scheduler] 任务 %s 已禁用，不注册", name)
            continue
        _scheduler.add_job(
            run_task,
            trigger=_cron_trigger(task["cron"]),
            args=[name],
            kwargs={"trigger": "scheduler"},
            id=f"sync_{name}",
            name=f"sync_{name}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info("[scheduler] 注册任务 %s cron=%s", name, task["cron"])
    _scheduler.start()
    logger.info("[scheduler] 后台调度器已启动")
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_status() -> list[dict]:
    """返回各任务调度信息（供 /sync/tasks 展示）"""
    jobs = {}
    if _scheduler is not None and _scheduler.running:
        for job in _scheduler.get_jobs():
            jobs[job.id] = job
    result = []
    for name, task in TASKS.items():
        job = jobs.get(f"sync_{name}")
        result.append(
            {
                "task_name": name,
                "description": task["description"],
                "cron": task["cron"],
                "enabled": task.get("enabled", True),
                "scheduled": job is not None,
                "next_run_time": job.next_run_time.isoformat() if (job and job.next_run_time) else None,
                "last_run": task_log_service.latest_status(name),
                "parameters": TASK_PARAMETERS.get(name, []),
            }
        )
    return result


if __name__ == "__main__":
    # 独立进程常驻启动（nohup python -m app.scheduler &）
    logger.info("=" * 60)
    logger.info("QuantMind 数据调度器独立进程启动")
    logger.info("=" * 60)
    try:
        start_scheduler()
    except Exception:  # noqa: BLE001
        logger.exception("调度器启动失败")
        raise
    # BackgroundScheduler 是非阻塞的，必须阻塞主线程保持进程存活
    import threading

    try:
        threading.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到退出信号，关闭调度器")
        shutdown_scheduler()
