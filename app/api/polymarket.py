# -*- coding: utf-8 -*-
"""Polymarket 预测市场信号 API"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import polymarket_sync as svc

router = APIRouter(prefix="/polymarket", tags=["Polymarket"])


@router.get("/signals", summary="查询 Polymarket 信号列表")
def list_signals(
    keyword: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    min_volume_usd: float | None = Query(None, ge=0),
):
    return {
        "count": 0,
        "data": svc.list_signals(keyword=keyword, limit=limit, min_volume_usd=min_volume_usd),
    }


@router.get("/signals/smart-money", summary="聪明钱信号")
def smart_money(limit: int = Query(20, ge=1, le=100)):
    return {"count": 0, "data": svc.get_smart_money_signals(limit=limit)}


@router.get("/signals/asset-suggestions", summary="资产配置建议")
def asset_suggestions(limit: int = Query(20, ge=1, le=100)):
    return {"count": 0, "data": svc.get_asset_suggestions(limit=limit)}


@router.post("/sync", summary="手动触发 Polymarket 同步")
def manual_sync(payload: dict | None = None):
    payload = payload or {}
    return svc.sync_polymarket(
        keywords=payload.get("keywords"),
        min_volume=float(payload.get("min_volume", 10000)),
        top_n=int(payload.get("top_n", 20)),
    )