# -*- coding: utf-8 -*-
"""市场情绪/风险指数查询接口（10周 DQN/情绪分析遗留表）"""
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from app.database import execute_query

router = APIRouter(prefix="/sentiment", tags=["市场情绪"])


@router.get("/aggregate", summary="查询个股情绪聚合数据")
def get_sentiment_aggregate(
    stock_code: str | None = Query(None, description="按股票代码过滤，如 600519（不传则查询全部）"),
    limit: int = Query(20, ge=1, le=200, description="返回记录条数上限，默认 20，最大 200"),
    auto_sync: bool = Query(True, description="数据不存在或过期时自动同步最新舆情"),
):
    """查询个股市场情绪聚合结果（sentiment_aggregate），包括恐惧贪婪指数等。

    **返回字段**：恐惧贪婪指数、整体情绪、正面/负面/中性新闻数量、核心主题、风险提示、
    机会提示、情绪摘要、新闻数量、分析时间。

    **使用说明**：
    - 按分析时间**倒序**返回（最新分析在前）
    - 数据由 `POST /sync/sentiment` 情感分析任务生成
    - 恐惧贪婪指数用于判断个股情绪处于恐慌还是贪婪区间
    - **自动同步**：指定股票代码时，如果数据不存在或超过1天未更新，自动同步最新舆情

    **示例**：`GET /sentiment/aggregate?stock_code=600519`
    """
    # 自动同步逻辑：仅在指定股票代码时触发
    if stock_code and auto_sync:
        latest = execute_query(
            "SELECT analyzed_at FROM sentiment_aggregate WHERE stock_code=%s ORDER BY analyzed_at DESC LIMIT 1",
            (stock_code,),
        )
        should_sync = False
        if not latest:
            should_sync = True
        else:
            last_time = latest[0]["analyzed_at"]
            if isinstance(last_time, str):
                last_time = datetime.fromisoformat(last_time)
            if datetime.now() - last_time > timedelta(days=1):
                should_sync = True

        if should_sync:
            # 步骤1: 同步新闻
            stock_info = execute_query(
                "SELECT stock_code, stock_name FROM trade_stock_status WHERE stock_code LIKE %s LIMIT 1",
                (f"{stock_code}%",),
            )
            if stock_info:
                from app.services.news_sync import sync_news
                from app.services.sentiment_sync import sync_sentiment_detail, sync_sentiment_aggregate

                stock_name = stock_info[0].get("stock_name", stock_code)
                sync_news(stock_codes=[(stock_code, stock_name)], limit_per_stock=50)
                time.sleep(1)
                # 步骤2: 情感分析
                sync_sentiment_detail(days=7)
                sync_sentiment_aggregate(days=7)
                time.sleep(1)

    sql = (
        "SELECT stock_code, fear_greed_index, overall_sentiment, positive_count, "
        "negative_count, neutral_count, top_themes, risk_alerts, "
        "opportunity_hints, summary, news_count, analyzed_at "
        "FROM sentiment_aggregate"
    )
    params: list = []
    if stock_code:
        sql += " WHERE stock_code=%s"
        params.append(stock_code)
    sql += " ORDER BY analyzed_at DESC LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    return {"count": len(rows), "data": rows}


@router.get("/detail", summary="查询新闻情绪明细")
def get_sentiment_detail(
    stock_code: str | None = Query(None, description="按股票代码过滤，如 600519（不传则查询全部）"),
    sentiment: str | None = Query(None, description="按情感过滤：positive（正面）/ negative（负面）/ neutral（中性）"),
    limit: int = Query(50, ge=1, le=500, description="返回记录条数上限，默认 50，最大 500"),
    auto_sync: bool = Query(True, description="数据不存在或过期时自动同步最新舆情"),
):
    """查询每条新闻的情绪分析明细（sentiment_detail）。

    **返回字段**：股票代码、新闻标题、新闻正文、情感倾向、情感强度、实体、关键词、
    摘要、市场影响、新闻来源、新闻日期、分析时间。

    **使用说明**：
    - 按分析时间**倒序**返回
    - 支持按股票代码与情感倾向组合过滤，用于追踪某只股票的最新舆论方向
    - 情感强度（strength）反映模型对判断的置信程度
    - **自动同步**：指定股票代码时，如果数据不存在或超过1天未更新，自动同步最新舆情

    **示例**：`GET /sentiment/detail?stock_code=600519&sentiment=negative`
    """
    # 自动同步逻辑
    if stock_code and auto_sync:
        latest = execute_query(
            "SELECT analyzed_at FROM sentiment_detail WHERE stock_code=%s ORDER BY analyzed_at DESC LIMIT 1",
            (stock_code,),
        )
        should_sync = False
        if not latest:
            should_sync = True
        else:
            last_time = latest[0]["analyzed_at"]
            if isinstance(last_time, str):
                last_time = datetime.fromisoformat(last_time)
            if datetime.now() - last_time > timedelta(days=1):
                should_sync = True

        if should_sync:
            stock_info = execute_query(
                "SELECT stock_code, stock_name FROM trade_stock_status WHERE stock_code LIKE %s LIMIT 1",
                (f"{stock_code}%",),
            )
            if stock_info:
                from app.services.news_sync import sync_news
                from app.services.sentiment_sync import sync_sentiment_detail, sync_sentiment_aggregate

                stock_name = stock_info[0].get("stock_name", stock_code)
                sync_news(stock_codes=[(stock_code, stock_name)], limit_per_stock=50)
                time.sleep(1)
                sync_sentiment_detail(days=7)
                sync_sentiment_aggregate(days=7)
                time.sleep(1)

    sql = (
        "SELECT stock_code, news_title, news_text, sentiment, strength, "
        "entities, keywords, summary, market_impact, news_source, news_date, analyzed_at "
        "FROM sentiment_detail"
    )
    params: list = []
    conds: list[str] = []
    if stock_code:
        conds.append("stock_code=%s")
        params.append(stock_code)
    if sentiment:
        conds.append("sentiment=%s")
        params.append(sentiment)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY analyzed_at DESC LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    return {"count": len(rows), "data": rows}


@router.get("/fear-index", summary="查询市场恐慌指数历史")
def get_fear_index(
    limit: int = Query(60, ge=1, le=500, description="返回历史记录条数上限，默认 60，最大 500"),
):
    """查询市场恐慌/贪婪指数历史（fear_index_history）。

    **返回字段**：VIX、OVX（原油波动率）、GVZ（黄金波动率）、美国10年期国债收益率、
    综合评分、风险等级、操作建议、记录时间。

    **使用说明**：
    - 按记录时间**倒序**返回（最新一天在前）
    - 综合评分基于 VIX/OVX/GVZ 等波动率指标合成，衡量整体市场恐慌程度
    - 风险等级与操作建议可直接作为仓位控制的参考依据

    **示例**：`GET /sentiment/fear-index?limit=30`
    """
    rows = execute_query(
        "SELECT vix, ovx, gvz, us10y, composite_score, risk_level, suggestion, recorded_at "
        "FROM fear_index_history ORDER BY recorded_at DESC LIMIT %s",
        (limit,),
    )
    return {"count": len(rows), "data": rows}


@router.get("/events", summary="查询市场事件（催化剂）")
def get_market_events(
    stock_code: str | None = Query(None, description="按股票代码过滤，如 600519（不传则查询全部）"),
    event_type: str | None = Query(None, description="按事件类型过滤，如 业绩/重组/政策/订单等"),
    limit: int = Query(50, ge=1, le=500, description="返回事件条数上限，默认 50，最大 500"),
    auto_sync: bool = Query(True, description="数据不存在或过期时自动同步最新事件"),
):
    """查询市场事件/催化剂（market_events），用于事件驱动策略。

    **返回字段**：股票代码、事件类型、事件子类型、事件描述、信号方向、新闻日期、创建时间。

    **使用说明**：
    - 按创建时间**倒序**返回（最新事件在前）
    - 数据由 `POST /sync/events` 事件识别任务生成
    - 事件可作为**催化剂**与五步分析法联动，辅助判断买卖时机
    - **自动同步**：指定股票代码时，如果数据不存在或超过1天未更新，自动同步最新事件

    **示例**：`GET /sentiment/events?stock_code=600519&event_type=业绩`
    """
    # 自动同步逻辑
    if stock_code and auto_sync:
        latest = execute_query(
            "SELECT created_at FROM market_events WHERE stock_code=%s ORDER BY created_at DESC LIMIT 1",
            (stock_code,),
        )
        should_sync = False
        if not latest:
            should_sync = True
        else:
            last_time = latest[0]["created_at"]
            if isinstance(last_time, str):
                last_time = datetime.fromisoformat(last_time)
            if datetime.now() - last_time > timedelta(days=1):
                should_sync = True

        if should_sync:
            stock_info = execute_query(
                "SELECT stock_code, stock_name FROM trade_stock_status WHERE stock_code LIKE %s LIMIT 1",
                (f"{stock_code}%",),
            )
            if stock_info:
                from app.services.news_sync import sync_news
                from app.services.sentiment_sync import sync_sentiment_detail, sync_sentiment_aggregate, sync_market_events

                stock_name = stock_info[0].get("stock_name", stock_code)
                sync_news(stock_codes=[(stock_code, stock_name)], limit_per_stock=50)
                time.sleep(1)
                sync_sentiment_detail(days=7)
                sync_sentiment_aggregate(days=7)
                time.sleep(1)
                sync_market_events(days=7)
                time.sleep(1)

    sql = (
        "SELECT stock_code, event_type, event_subtype, event_desc, `signal`, "
        "news_date, created_at FROM market_events"
    )
    params: list = []
    conds: list[str] = []
    if stock_code:
        conds.append("stock_code=%s")
        params.append(stock_code)
    if event_type:
        conds.append("event_type=%s")
        params.append(event_type)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    return {"count": len(rows), "data": rows}
