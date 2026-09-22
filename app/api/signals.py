# -*- coding: utf-8 -*-
"""缠论信号查询接口。"""
from fastapi import APIRouter, Query

from app.signals import SignalStore

router = APIRouter(prefix="/signals", tags=["缠论信号"])


@router.get("", summary="查询缠论信号")
def list_signals(
    stock_code: str | None = Query(None),
    signal_type: str | None = Query(None, description="first_buy/second_buy/third_buy/first_sell/second_sell/third_sell"),
    status: str | None = Query(None),
):
    rows = SignalStore().list(stock_code=stock_code, signal_type=signal_type, status=status)
    return {"count": len(rows), "data": rows}
