"""Independent risk-control API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.risk_control import acknowledge_alert, evaluate, list_alerts, list_decisions

router = APIRouter(prefix="/risk", tags=["独立风控"])


class RiskCheckRequest(BaseModel):
    stock_code: str | None = Field(None, min_length=1)
    action: str = Field("buy", pattern="^(buy|sell)$")
    target_weight: float | None = Field(None, ge=0, le=1)
    industry_weight: float | None = Field(None, ge=0, le=1)
    portfolio_id: str = Field("default", min_length=1, max_length=64)
    portfolio: dict = Field(default_factory=dict)
    rules: dict = Field(default_factory=dict)


@router.post("/check", summary="执行独立风控检查")
def check_risk(payload: RiskCheckRequest):
    return evaluate(payload.model_dump())


@router.get("/status", summary="查询最新风控状态")
def risk_status():
    decisions = list_decisions(limit=1)
    alerts = list_alerts(limit=20)
    latest = decisions[0] if decisions else None
    return {"decision": latest, "active_alerts": alerts, "data_quality": "unknown" if latest is None else "available"}


@router.get("/alerts", summary="查询风险预警")
def risk_alerts(status: str | None = Query("active"), limit: int = Query(100, ge=1, le=500)):
    rows = list_alerts(status=status, limit=limit)
    return {"count": len(rows), "data": rows}


@router.post("/alerts/{alert_id}/acknowledge", summary="确认风险预警")
def acknowledge_risk_alert(alert_id: int):
    if not acknowledge_alert(alert_id):
        raise HTTPException(status_code=404, detail="风险预警不存在或已处理")
    return {"id": alert_id, "status": "acknowledged"}


@router.get("/decisions", summary="查询风控决策历史")
def risk_decisions(limit: int = Query(100, ge=1, le=500)):
    rows = list_decisions(limit=limit)
    return {"count": len(rows), "data": rows}
