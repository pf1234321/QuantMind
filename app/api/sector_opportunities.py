# -*- coding: utf-8 -*-
"""板块选股机会 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.sector_opportunity import (
    get_sector_opportunity,
    get_sector_opportunity_candidates,
    list_sector_opportunity_history,
    list_sector_opportunities,
    scan_sector_opportunities,
)

router = APIRouter(prefix="/sector-opportunities", tags=["板块选股机会"])
_ALLOWED_PHASES = {"accel_up", "decel_up", "accel_down", "decel_down", "neutral"}


@router.post("/scan", summary="扫描板块选股机会")
def scan(
    level: int = Query(2, ge=1, le=2, description="申万层级：1=一级，2=二级"),
    end_date: str | None = Query(None, description="截止日期，默认板块数据最新交易日"),
    top_n: int = Query(5, ge=1, le=50, description="每个板块输出候选股票数"),
    top_sector_n: int = Query(10, ge=1, le=100, description="参与机会筛选的板块排名范围"),
    sector_names: str | None = Query(None, description="自定义申万二级板块名称，多个名称用逗号分隔"),
):
    try:
        names = sector_names.split(",") if sector_names and sector_names.strip() else None
        return scan_sector_opportunities(level=level, end_date=end_date, top_n=top_n, top_sector_n=top_sector_n, sector_names=names)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", summary="查询板块选股机会")
def list_opportunities(
    level: int | None = Query(2, ge=1, le=2, description="固定使用申万二级板块"),
    sector_name: str | None = Query(None, description="板块名称关键词，支持模糊匹配"),
    phase: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    min_rank: int | None = Query(None, ge=1),
    max_rank: int | None = Query(None, ge=1),
    min_stock_score: float | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    phase = phase or None
    if phase is not None and phase not in _ALLOWED_PHASES:
        raise HTTPException(status_code=422, detail="phase must be one of accel_up, decel_up, accel_down, decel_down, neutral")
    return list_sector_opportunities(level, sector_name, phase, start_date, end_date, page, page_size, min_rank, max_rank, min_stock_score)


@router.get("/history", summary="查询板块机会历史")
def history(
    sector_name: str | None = Query(None),
    level: int | None = Query(2, ge=1, le=2, description="默认使用申万二级板块"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    confirmation_status: str | None = Query(None),
):
    return list_sector_opportunity_history(sector_name, level, start_date, end_date, confirmation_status)


@router.get("/{opportunity_id}/candidates", summary="查询板块机会候选股票")
def candidates(opportunity_id: int):
    return get_sector_opportunity_candidates(opportunity_id)


@router.get("/{opportunity_id}", summary="查询板块机会详情")
def detail(opportunity_id: int):
    try:
        return get_sector_opportunity(opportunity_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
