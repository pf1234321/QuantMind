"""风险告警与交易计划接口。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.risk_control import evaluate
from app.signals import SignalStore
from app.trade_plans import TradePlanStore

router = APIRouter(tags=["风险与交易计划"])


class TradePlanCreate(BaseModel):
    stock_code: str = Field(..., min_length=1)
    action: str = Field(..., pattern="^(buy|sell)$")
    target_weight: float | None = Field(None, ge=0, le=1)
    reason: str | None = None
    signal_id: str | None = None
    signal_date: str | None = None


@router.get("/risks", summary="查询风险信号")
def list_risks(stock_code: str | None = Query(None), limit: int = Query(100, ge=1, le=500)):
    signals = SignalStore().list(stock_code=stock_code)
    risks = [row for row in signals if str(row.get("signal_type", "")).endswith("sell")]
    return {"count": len(risks[:limit]), "data": risks[:limit], "signal_mode": "strict_no_lookahead"}


@router.get("/trade-plans", summary="查询交易计划")
def list_trade_plans(
    status: str | None = Query(None),
    stock_code: str | None = Query(None),
    action: str | None = Query(None),
    stock_keyword: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
):
    rows = TradePlanStore().list(
        status=status,
        stock_code=stock_code,
        action=action,
        stock_keyword=stock_keyword,
        start_date=start_date,
        end_date=end_date,
    )
    start = (page - 1) * page_size
    return {"count": len(rows), "page": page, "page_size": page_size, "data": rows[start:start + page_size]}


@router.post("/trade-plans", summary="创建交易计划", status_code=201)
def create_trade_plan(payload: TradePlanCreate):
    data = payload.model_dump()
    risk = evaluate(data)
    data.update({
        "risk_decision": risk["decision"],
        "risk_level": risk["risk_level"],
        "risk_snapshot_json": json.dumps(risk, ensure_ascii=False, default=str),
    })
    item = TradePlanStore().create(data)
    item["risk"] = risk
    return item


def _change_plan_status(plan_id: str, status: str):
    store = TradePlanStore()
    item = store.get(plan_id)
    if item is None:
        raise HTTPException(status_code=404, detail="交易计划不存在")
    if status == "accepted":
        risk = evaluate({
            "stock_code": item["stock_code"],
            "action": item["action"],
            "target_weight": item.get("target_weight"),
        })
        store.update_risk(plan_id, risk)
        if risk["decision"] in {"REJECT", "HALT"}:
            raise HTTPException(status_code=409, detail={"message": "风控未通过，无法接受交易计划", "risk": risk})
    item = store.update_status(plan_id, status)
    if item is None:
        raise HTTPException(status_code=404, detail="交易计划不存在")
    return item


@router.post("/trade-plans/{plan_id}/accept", summary="接受交易计划")
def accept_trade_plan(plan_id: str):
    return _change_plan_status(plan_id, "accepted")


@router.post("/trade-plans/{plan_id}/reject", summary="拒绝交易计划")
def reject_trade_plan(plan_id: str):
    return _change_plan_status(plan_id, "rejected")
