# -*- coding: utf-8 -*-
"""宏观/利率/日历/板块 查询接口"""
from fastapi import APIRouter, HTTPException, Query

from app.database import execute_query

router = APIRouter(prefix="/market", tags=["市场数据"])


@router.get("/macro", summary="查询月度宏观指标")
def get_macro(
    start_date: str | None = Query(None, description="起始日期（月度），格式 YYYYMM，如 202401"),
    end_date: str | None = Query(None, description="结束日期（月度），格式 YYYYMM，如 202412"),
    limit: int = Query(60, ge=1, le=500, description="返回指标记录条数上限，默认 60，最大 500"),
):
    """查询月度宏观指标宽表（trade_macro_indicator）。

    **返回字段**：统计月份、CPI同比、PPI同比、PMI、M2同比、社会融资规模、1年期LPR、5年期LPR、数据来源。

    **使用说明**：
    - 按统计月份**倒序**返回（最新月份在最前面）
    - 用于宏观环境判断与自上而下（Top-down）投资研究

    **示例**：`GET /market/macro?start_date=202401&end_date=202412`
    """
    sql = (
        "SELECT indicator_date, cpi_yoy, ppi_yoy, pmi, m2_yoy, shrzgm, "
        "lpr_1y, lpr_5y, data_source FROM trade_macro_indicator"
    )
    params: list = []
    conds: list[str] = []
    if start_date:
        conds.append("indicator_date>=%s")
        params.append(start_date)
    if end_date:
        conds.append("indicator_date<=%s")
        params.append(end_date)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY indicator_date DESC LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    if not rows:
        raise HTTPException(404, "未找到宏观指标数据")
    return {"count": len(rows), "data": rows}


@router.get("/rates", summary="查询日频国债收益率")
def get_rates(
    start_date: str | None = Query(None, description="起始日期，格式 YYYYMMDD，如 20240101"),
    end_date: str | None = Query(None, description="结束日期，格式 YYYYMMDD，如 20241231"),
    limit: int = Query(60, ge=1, le=500, description="返回利率记录条数上限，默认 60，最大 500"),
):
    """查询日频国债收益率（trade_rate_daily）。

    **返回字段**：日期、中国10年期国债收益率、美国10年期国债收益率、数据来源。

    **使用说明**：
    - 按日期**倒序**返回（最新一天在最前面）
    - 中美国债利差是汇率与资金流向的重要参考指标
    - 可用于判断无风险利率环境对资产定价的影响

    **示例**：`GET /market/rates?limit=30`
    """
    sql = "SELECT rate_date, cn_bond_10y, us_bond_10y, data_source FROM trade_rate_daily"
    params: list = []
    conds: list[str] = []
    if start_date:
        conds.append("rate_date>=%s")
        params.append(start_date)
    if end_date:
        conds.append("rate_date<=%s")
        params.append(end_date)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY rate_date DESC LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    if not rows:
        raise HTTPException(404, "未找到利率数据")
    return {"count": len(rows), "data": rows}


@router.get("/calendar", summary="查询财经日历事件")
def get_calendar(
    start_date: str | None = Query(None, description="起始日期，格式 YYYYMMDD，如 20240101"),
    end_date: str | None = Query(None, description="结束日期，格式 YYYYMMDD，如 20241231"),
    country: str | None = Query(None, description="按国家/地区过滤，如 CN（中国）/ US（美国）"),
    importance: int | None = Query(None, ge=1, le=3, description="按重要程度过滤：3=高 / 2=中 / 1=低"),
    category: str | None = Query(None, description="按事件类别过滤，如 宏观数据 / 央行动态 / 财报"),
    limit: int = Query(100, ge=1, le=500, description="返回事件条数上限，默认 100，最大 500"),
):
    """查询财经日历事件（trade_calendar_event），用于把握重要时间节点。

    **返回字段**：事件日期、事件时间、国家、类别、标题、重要程度、前值、预测值、实际值、影响、来源、状态。

    **使用说明**：
    - 按事件时间**升序**返回（即将发生的事件在前面）
    - 支持国家、重要程度、类别多条件组合过滤
    - 重要数据发布（如非农、CPI、LPR）前后往往是行情波动窗口

    **示例**：`GET /market/calendar?country=CN&importance=3&start_date=20240801&end_date=20240831`
    """
    sql = (
        "SELECT event_date, event_time, country, category, title, importance, "
        "previous_value, forecast_value, actual_value, impact, source, status "
        "FROM trade_calendar_event"
    )
    params: list = []
    conds: list[str] = []
    if start_date:
        conds.append("event_date>=%s")
        params.append(start_date)
    if end_date:
        conds.append("event_date<=%s")
        params.append(end_date)
    if country:
        conds.append("country=%s")
        params.append(country)
    if importance:
        conds.append("importance>=%s")
        params.append(importance)
    if category:
        conds.append("category=%s")
        params.append(category)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY event_date ASC, event_time ASC LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    if not rows:
        raise HTTPException(404, "未找到日历事件")
    return {"count": len(rows), "data": rows}


@router.get("/sectors", summary="查询板块行情数据")
def get_sectors(
    level: int = Query(2, ge=1, le=2, description="板块级别：1=申万一级（行业大类）/ 2=申万二级（细分行业），默认 2"),
    name: str | None = Query(None, description="板块名称（精确匹配），如 白酒 / 半导体"),
    trade_date: str | None = Query(None, description="指定交易日 YYYYMMDD，不传则返回全部日期"),
    limit: int = Query(100, ge=1, le=500, description="返回记录条数上限，默认 100，最大 500"),
):
    """查询板块每日聚合行情（trade_sector_daily，等权合成指数）。

    **返回字段**：板块代码/名称、级别、交易日及当日聚合后的涨跌幅、成交等指标。

    **使用说明**：
    - 按交易日**倒序**返回（最新交易日在前）
    - 板块数据需先通过 `POST /sync/sectors` 聚合生成，若查不到数据请先执行同步
    - 用于板块轮动分析与行业配置研究

    **示例**：`GET /market/sectors?level=2&name=白酒&limit=10`
    """
    sql = "SELECT * FROM trade_sector_daily WHERE sector_level=%s"
    params: list = [level]
    if name:
        sql += " AND sector_name=%s"
        params.append(name)
    if trade_date:
        sql += " AND trade_date=%s"
        params.append(trade_date)
    sql += " ORDER BY trade_date DESC LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    if not rows:
        raise HTTPException(404, "未找到板块数据，请先运行板块聚合")
    return {"level": level, "count": len(rows), "data": rows}


@router.get("/sectors/names", summary="查询板块名称列表")
def get_sector_names(
    level: int = Query(2, ge=1, le=2, description="板块级别：1=申万一级 / 2=申万二级，默认 2"),
):
    """查询指定级别下的全部板块名称列表（去重）。

    **使用说明**：
    - 返回结果可直接用于前端下拉选择或板块过滤
    - 可通过 name 参数与 `GET /market/sectors` 配合查询具体板块行情

    **示例**：`GET /market/sectors/names?level=2`
    """
    rows = execute_query(
        "SELECT DISTINCT sector_name FROM trade_sector_daily WHERE sector_level=%s ORDER BY sector_name",
        (level,),
    )
    return {"level": level, "count": len(rows), "data": [r["sector_name"] for r in rows]}
