"""回测执行与结果查询接口。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from app.backtest.runner import scan_atr_exit_mult
from app.strategy.atr_chan import build_internal_adapter

router = APIRouter(prefix="/backtest", tags=["回测"])


def _records(frame):
    if frame is None or frame.empty:
        return []
    return frame.where(frame.notna(), None).to_dict(orient="records")


@router.post("/run", summary="执行 ATR 缠论回测")
def run_backtest(payload: dict):
    stock_code = str(payload.get("stock_code", "600519"))
    start_date = str(payload.get("start_date", "2022-01-01"))
    end_date = str(payload.get("end_date", date.today().isoformat()))
    try:
        result = scan_atr_exit_mult(
            stock_code=stock_code,
            start_date=start_date,
            end_date=end_date,
            multipliers=payload.get("multipliers"),
            range_start=payload.get("range_start"),
            range_end=payload.get("range_end"),
            step=payload.get("step"),
            adapter=build_internal_adapter(),
            evaluate_periods=bool(payload.get("evaluate_periods", False)),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"report": result.report, "summary": _records(result.summary), "trades": _records(result.trades), "equity": _records(result.equity)}
