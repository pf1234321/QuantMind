# -*- coding: utf-8 -*-
"""数据同步触发接口（对应 services 层各同步模块 + 定时任务管理）

- 原有 /sync/{task} 全部接入 scheduler.run_task，执行情况自动写入 sync_task_log
- 新增 /sync/tasks、/sync/logs、/sync/run/{task} 供查看调度与手动触发
"""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query

from app import scheduler
from app.database import execute_query
from app.services import task_log_service

router = APIRouter(prefix="/sync", tags=["数据同步"])


def _default_stocks(limit: int = 100) -> list[tuple[str, str]]:
    """默认从 trade_stock_status 取前 N 只股票"""
    rows = execute_query(
        "SELECT stock_code, stock_name FROM trade_stock_status WHERE stock_name IS NOT NULL LIMIT %s",
        (limit,),
    )
    return [(r["stock_code"].split(".")[0], r["stock_name"]) for r in rows]


def _stocks_by_codes(codes: list[str]) -> list[tuple[str, str]]:
    """根据用户指定的股票代码查询股票名称，并校验股票是否存在。"""
    normalized = list(dict.fromkeys(code.strip().upper().split(".")[0] for code in codes if code.strip()))
    if not normalized:
        raise HTTPException(status_code=422, detail="stocks 不能为空")

    placeholders = ", ".join(["%s"] * len(normalized))
    rows = execute_query(
        f"SELECT stock_code, stock_name FROM trade_stock_status "
        f"WHERE REPLACE(stock_code, '.SH', '') IN ({placeholders}) "
        f"OR REPLACE(stock_code, '.SZ', '') IN ({placeholders})",
        normalized + normalized,
    )
    found = {
        str(row["stock_code"]).upper().split(".")[0]: row.get("stock_name") or code
        for row in rows
        for code in [str(row["stock_code"]).upper().split(".")[0]]
    }
    missing = [code for code in normalized if code not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"股票不存在: {', '.join(missing)}")
    return [(code, found[code]) for code in normalized]


def _run(task_name: str, trigger: str = "api", **kwargs) -> dict:
    """统一执行 + 日志；失败返回结构化错误（200），成功返回结果"""
    try:
        out = scheduler.run_task(task_name, trigger=trigger, **kwargs)
        return {"task": out["task"], "log_id": out["log_id"], "status": out["status"], "result": out["result"]}
    except Exception as exc:  # noqa: BLE001
        # 日志已由 run_task 记录 failed
        return {"task": task_name, "status": "failed", "error": str(exc)}


# ===================== 原同步接口（接入日志） =====================

@router.post("/kline", summary="同步K线日线数据")
def sync_kline(
    stocks: Optional[list[str]] = Query(None, description="指定股票代码列表，如 [\"600519\", \"000001\"]；不传则按默认股票池全量同步"),
    start_date: Optional[str] = Query(None, description="重写起始日期；与 force_refresh=true 一起使用"),
    end_date: Optional[str] = Query(None, description="重写结束日期；默认今天"),
    force_refresh: bool = Query(False, description="是否强制重写历史行情，避免沿用旧错误数据"),
):
    """同步日K线行情数据到 trade_stock_daily 表（baostock 数据源）。

    **使用说明**：
    - 股票代码自动按规则补充交易所后缀（6/9 开头 -> .SH，其余 -> .SZ）
    - 不传 stocks 时同步全部已收录股票
    - 执行结果自动写入 sync_task_log，可通过 `GET /sync/logs` 查询

    **示例**：`POST /sync/kline?stocks=600519&stocks=000001`
    """
    codes = [s.split(".")[0] + (".SH" if s.startswith(("6", "9")) else ".SZ") for s in stocks] if stocks else None
    return _run("kline", stock_codes=codes, start_date=start_date,
                end_date=end_date, force_refresh=force_refresh)


@router.post("/financial", summary="同步财务数据")
def sync_financial(
    stocks: Optional[list[str]] = Query(None, description="指定股票代码列表；不传则同步 AkShare 返回的全部股票"),
    quarters: int = Query(2, ge=1, le=12, description="同步最近几个报告期，默认 2 个季度"),
    enrich_detail: bool = Query(False, description="是否逐股补全 ROA、净利率、资产负债率等明细指标；股票较多时耗时较长"),
    test_mode: bool = Query(False, description="测试模式，仅同步少量预设股票和最近 1 个报告期"),
):
    """同步财务数据到 trade_stock_financial 表（akshare 跨平台数据源）。

    **使用说明**：
    - 不传 stocks 时，同步 AkShare 业绩报表返回的全部股票
    - 传 stocks 时，仅同步指定股票；代码可重复传参
    - enrich_detail=true 时逐股拉取财务摘要，补全明细指标，建议仅用于少量股票
    - 执行结果自动写入 sync_task_log，可通过 `GET /sync/logs` 查看

    **示例**：`POST /sync/financial?stocks=600519&stocks=000001&quarters=4&enrich_detail=true`
    """
    stock_codes = [s.strip().upper().split(".")[0] for s in stocks or [] if s.strip()] or None
    return _run(
        "financial",
        stock_codes=stock_codes,
        quarters=quarters,
        enrich_detail=enrich_detail,
        test_mode=test_mode,
    )


@router.post("/macro", summary="同步宏观指标与利率")
def sync_macro():
    """同步月度宏观指标与日频国债收益率（trade_macro_indicator / trade_rate_daily）。

    **使用说明**：
    - 同步内容包括：CPI、PPI、PMI、M2、社融、LPR 以及中美国债收益率
    - 同步完成后可通过 `GET /market/macro`、`GET /market/rates` 查询
    """
    return _run("macro")


@router.post("/news", summary="同步个股新闻")
def sync_news(
    stocks: Optional[list[str]] = Query(None, description="指定股票代码列表，如 600519、000001；可重复传参；不传则按默认股票池同步"),
    limit: int = Query(100, ge=1, le=5000, description="未指定 stocks 时，参与同步的股票数量上限"),
    limit_per_stock: int = Query(50, ge=1, le=200, description="每只股票最多同步的新闻条数"),
):
    """同步个股新闻到 trade_stock_news 表。"""
    stock_codes = _stocks_by_codes(stocks) if stocks else _default_stocks(limit)
    return _run("news", stock_codes=stock_codes, limit=limit, limit_per_stock=limit_per_stock)


@router.post("/report", summary="同步研报一致预期")
def sync_report(
    limit: int = Query(100, ge=1, le=5000, description="参与同步的股票数量上限，默认 100，最大 5000"),
):
    """同步券商研报一致预期数据到 trade_report_consensus 表。

    **使用说明**：
    - 抓取券商对个股的评级、目标价与盈利预测
    - 同步完成后可通过 `GET /stocks/consensus`、`GET /stocks/factors` 查询
    """
    return _run("report", stock_codes=_default_stocks(limit), limit=limit)


@router.post("/calendar", summary="同步财经日历")
def sync_calendar(
    start_date: Optional[str] = Query(None, description="起始日期 YYYYMMDD，如 20240801"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD，如 20240831"),
):
    """同步财经日历事件到 trade_calendar_event 表。

    **使用说明**：
    - 不传日期时默认同步当前时间窗口的日历
    - 同步完成后可通过 `GET /market/calendar` 查询
    """
    return _run("calendar", start_date=start_date, end_date=end_date)


@router.post("/industry", summary="同步申万行业分类")
def sync_industry(
    fetch_shares: bool = Query(True, description="是否同时更新股本数据（总股本/流通股本），默认 True"),
):
    """同步申万行业分类到 trade_stock_status 表。

    **使用说明**：
    - 更新每只股票的申万一级/二级/三级行业归属
    - fetch_shares=true 时同时刷新总股本与流通股本
    - 同步完成后可通过 `GET /stocks/list` 查询
    """
    return _run("industry", fetch_shares=fetch_shares)


@router.post("/sectors", summary="板块聚合重算")
def sync_sectors(
    level: int = Query(2, ge=1, le=2, description="板块级别：1=申万一级 / 2=申万二级，默认 2"),
    days: Optional[int] = Query(30, ge=1, description="重算最近 N 个交易日的板块聚合数据，默认 30"),
    full: bool = Query(False, description="是否全量重算（忽略 days 限制），默认 False"),
):
    """重算板块每日聚合行情到 trade_sector_daily 表（等权合成指数）。

    **使用说明**：
    - 基于个股日K线按行业分类等权合成板块指数
    - 板块行情数据未生成时，`GET /market/sectors` 会返回 404，需先执行本接口
    - full=true 时执行全量重算（耗时较长）
    """
    return _run("sectors", level=level, days=days, full=full)


@router.post("/catalyst", summary="同步催化剂事件")
def sync_catalyst():
    """同步关键催化剂事件（Qwen Max 联网分析，需配置 DASHSCOPE_API_KEY）。

    **使用说明**：
    - 通过大模型联网检索并提炼市场关键催化剂事件
    - **前置条件**：环境变量需配置 DASHSCOPE_API_KEY，否则任务会失败
    """
    return _run("catalyst")


@router.post("/sentiment", summary="新闻情感分析与情绪聚合")
def sync_sentiment(
    days: int = Query(7, ge=1, le=30, description="分析最近 N 天的新闻，默认 7 天"),
    limit: int = Query(200, ge=1, le=2000, description="参与分析的新闻条数上限，默认 200，最大 2000"),
):
    """对新闻执行情感分析并生成个股情绪聚合结果（sentiment_detail / sentiment_aggregate）。

    **使用说明**：
    - 逐条新闻打情感标签（正面/负面/中性）并给出强度与摘要
    - 按个股聚合出恐惧贪婪指数、核心主题、风险/机会提示
    - 同步完成后可通过 `GET /sentiment/detail`、`GET /sentiment/aggregate` 查询
    """
    return _run("sentiment", days=days, limit=limit)


@router.post("/events", summary="市场事件识别")
def sync_events(
    days: int = Query(7, ge=1, le=30, description="分析最近 N 天的新闻素材，默认 7 天"),
):
    """从新闻中识别市场事件/催化剂并写入 market_events 表。

    **使用说明**：
    - 识别事件类型、子类型与信号方向（利好/利空）
    - 同步完成后可通过 `GET /sentiment/events` 查询
    - 依赖新闻与情绪分析数据，建议先执行 /sync/news、/sync/sentiment
    """
    return _run("events", days=days)


@router.post("/fear-index", summary="同步市场恐慌/贪婪指数")
def sync_fear_index(
    days: int = Query(3, ge=1, le=30, description="计算最近 N 天的恐慌指数，默认 3 天"),
):
    """计算并写入市场恐慌/贪婪指数（fear_index_history）。

    **使用说明**：
    - 基于 VIX/OVX/GVZ 等波动率指标合成综合评分与风险等级
    - 同步完成后可通过 `GET /sentiment/fear-index` 查询
    """
    return _run("fear_index", days=days)


@router.post("/announcement", summary="同步全市场公告")
def sync_announcement(
    start_date: Optional[str] = Query(None, description="起始日期 YYYYMMDD，默认今天向前 3 天"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD，默认今天"),
    lookback_days: int = Query(3, ge=1, le=30, description="向前回看天数，默认 3 天"),
):
    """增量同步东方财富全市场公告到 trade_stock_announcement 表。

    **使用说明**：
    - 增量模式：默认同步最近 3 天（可用 lookback_days 调整）
    - 同步完成后可通过 `GET /stocks/announcements` 查询
    """
    return _run("announcement", start_date=start_date, end_date=end_date, lookback_days=lookback_days)


@router.post("/announcement/track", summary="同步股票池公告追踪")
def sync_announcement_track(
    stocks: Optional[list[str]] = Query(None, description="股票代码列表，如 [\"600519\", \"000001\"]；默认取股票池前 100 只"),
    lookback_days: int = Query(7, ge=1, le=60, description="向前回看天数，默认 7 天"),
    only_important: bool = Query(False, description="是否只保留重要公告（业绩预告/解禁/股权变动等）"),
    categories: Optional[str] = Query(None, description="巨潮官方公告分类，逗号分隔，如：业绩预告,解禁,股权变动；不传则全量"),
):
    """按股票池追踪巨潮资讯（cninfo）公告并写入 trade_stock_announcement 表。

    **与 /sync/announcement 的区别**：
    - 本接口针对**指定股票池**做深挖追踪，支持分类过滤
    - 可只保留重要公告，减少噪音

    **示例**：`POST /sync/announcement/track?stocks=600519&stocks=000001&only_important=true&categories=业绩预告,解禁`
    """
    codes = [s.split(".")[0] for s in stocks] if stocks else None
    cats = [c.strip() for c in categories.split(",")] if categories else []
    return _run("ann_track", stock_codes=codes, lookback_days=lookback_days,
                only_important=only_important, categories=cats)


@router.post("/all", summary="全量数据同步")
def sync_all():
    """一键执行全量同步（行业 -> K线 -> 板块 -> 新闻/研报/宏观/日历，逐步记录日志）。

    **执行顺序**（每个步骤都会写入 sync_task_log）：
    1. 行业分类同步
    2. 日K线数据同步
    3. 板块聚合重算
    4. 新闻 / 研报一致预期
    5. 宏观指标与利率
    6. 财经日历

    **注意**：全量同步耗时较长，请合理安排触发时间；如需更精细控制，请分别调用各同步接口。
    """
    results = scheduler.run_all(trigger="api")
    return {"task": "all", "steps": results}


# ===================== 定时任务管理接口 =====================

@router.get("/tasks", summary="查看定时任务列表")
def list_tasks():
    """查看所有已注册的定时任务（cron 表达式、下次运行时间、最近一次执行情况）。

    **使用说明**：
    - 用于监控调度器运行状态
    - 手动触发单个任务请使用 `POST /sync/run/{task_name}`
    """
    return {"tasks": scheduler.scheduler_status()}


@router.get("/logs", summary="查询同步任务执行日志")
def list_logs(
    task_name: Optional[str] = Query(None, description="按任务名过滤，如 kline / news / sentiment"),
    status: Optional[str] = Query(None, description="按执行状态过滤：running（执行中）/ success（成功）/ failed（失败）/ skipped（跳过）"),
    started_after: Optional[str] = Query(None, description="开始时间下限，格式 YYYY-MM-DD HH:mm:ss"),
    started_before: Optional[str] = Query(None, description="开始时间上限，格式 YYYY-MM-DD HH:mm:ss"),
    limit: int = Query(50, ge=1, le=500, description="返回日志条数上限，默认 50，最大 500"),
    offset: int = Query(0, ge=0, description="分页偏移量，从 0 开始，配合 limit 翻页"),
):
    """查询数据同步任务的执行日志（sync_task_log）。

    **使用说明**：
    - 支持按任务名与状态组合过滤
    - 用于排查同步失败原因、查看任务耗时
    - 每个同步接口的调用都会产生一条日志记录

    **示例**：`GET /sync/logs?task_name=news&status=success&limit=20`
    """
    total, logs = task_log_service.list_logs(
        task_name, status, started_after, started_before, limit, offset
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": logs,
    }


@router.get("/overview", summary="同步中心概览")
def get_sync_overview():
    """返回今日执行统计及各任务汇总。"""
    return task_log_service.overview()


@router.get("/logs/{log_id}", summary="查询单条执行日志")
def get_log_detail(log_id: int):
    log = task_log_service.get_log(log_id)
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")
    return log


@router.get("/logs/summary", summary="查看任务执行概况")
def logs_summary():
    """统计每个任务最近的整体执行概况：运行次数、成功/失败次数、最近一次运行时间。

    **使用说明**：
    - 快速掌握各数据同步任务的健康度（成功率）
    - 与 `GET /sync/logs` 配合可下钻查看详细日志
    """
    return {"summary": task_log_service.summary()}


@router.post("/run/{task_name}", summary="手动触发定时任务")
def run_task(background_tasks: BackgroundTasks, task_name: str, parameters: Optional[dict] = Body(None, description="任务参数；参数定义可从 GET /sync/tasks 获取")):
    """手动立即触发任务，支持传入任务专属参数。"""
    if task_name not in scheduler.TASKS:
        raise HTTPException(status_code=404, detail=f"未知任务: {task_name}，可用任务: {list(scheduler.TASKS.keys())}")
    definitions = scheduler.TASK_PARAMETERS.get(task_name, [])
    values = parameters or {}
    allowed = {item["name"] for item in definitions}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise HTTPException(status_code=422, detail=f"不支持的参数: {', '.join(unknown)}")
    for item in definitions:
        name = item["name"]
        value = values.get(name)
        if item.get("required") and (value is None or value == "" or value == []):
            raise HTTPException(status_code=422, detail=f"参数“{item['label']}”为必填项")
        if value is not None and item.get("type") == "integer":
            try:
                values[name] = int(value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"参数“{item['label']}”必须是整数") from exc
            if "min" in item and values[name] < item["min"] or "max" in item and values[name] > item["max"]:
                raise HTTPException(status_code=422, detail=f"参数“{item['label']}”超出允许范围")
        if item.get("type") == "string_list" and isinstance(value, str):
            values[name] = [part for part in value.replace(',', ' ').split() if part]
    background_tasks.add_task(_run, task_name, trigger="manual", **values)
    return {"task": task_name, "status": "queued", "message": "同步任务已提交，页面将持续刷新执行状态"}
