# -*- coding: utf-8 -*-
"""舆情监控列表 API"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services import sentiment_watchlist as svc

router = APIRouter(prefix="/sentiment/watchlist", tags=["舆情监控列表"])


@router.get("/", summary="查询监控列表")
def list_items(
    group: str = Query("default", description="分组名"),
    enabled_only: bool = Query(True),
):
    items = svc.list_watch(group=group, enabled_only=enabled_only)
    return {"count": len(items), "data": items}


@router.post("/", summary="添加监控项")
def add_item(payload: dict[str, Any]):
    code = payload.get("stock_code")
    if not code:
        raise HTTPException(400, "stock_code 不能为空")
    try:
        item = svc.add_watch(
            group=payload.get("group_name") or "default",
            stock_code=code,
            stock_name=payload.get("stock_name"),
            threshold_fgi_low=payload.get("threshold_fgi_low"),
            threshold_fgi_high=payload.get("threshold_fgi_high"),
            threshold_negative_count=payload.get("threshold_negative_count"),
            note=payload.get("note"),
            enabled=payload.get("enabled", True),
        )
        return item
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/{group}/{stock_code}", summary="更新监控项")
def update_item(group: str, stock_code: str, payload: dict[str, Any]):
    item = svc.update_watch(group, stock_code, **payload)
    if not item:
        raise HTTPException(404, "监控项不存在")
    return item


@router.delete("/{group}/{stock_code}", summary="删除监控项")
def delete_item(group: str, stock_code: str):
    ok = svc.remove_watch(group, stock_code)
    return {"deleted": ok}


@router.get("/alerts", summary="监控列表告警聚合")
def get_alerts(group: str = Query("default")):
    return svc.get_alerts(group=group)