"""首页 Dashboard 聚合接口。"""
from __future__ import annotations

from fastapi import APIRouter

from app.signals import SignalStore
from app import scheduler

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _signals() -> list[dict]:
    try:
        return SignalStore().list()
    except Exception:
        return []


@router.get("/overview", summary="查询首页概览")
def overview():
    rows = _signals()
    buy = [row for row in rows if str(row.get("signal_type", "")).endswith("buy")]
    sell = [row for row in rows if str(row.get("signal_type", "")).endswith("sell")]
    return {
        "signal_mode": "strict_no_lookahead",
        "signal_summary": {"total": len(rows), "buy_count": len(buy), "sell_count": len(sell), "opportunity_count": len(buy), "risk_count": len(sell)},
        "top_opportunities": sorted(buy, key=lambda row: str(row.get("signal_date") or ""), reverse=True)[:10],
        "risk_alerts": sorted(sell, key=lambda row: str(row.get("signal_date") or ""), reverse=True)[:10],
        "system_status": {"scheduler_enabled": scheduler.scheduler_status()},
    }
