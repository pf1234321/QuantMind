"""ATR 参数版本和季度报告查询接口。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.backtest.data import load_daily_bars
from app.backtest.parameters import ParameterState
from app.backtest.quarterly import QuarterlyParameterService
from app.backtest.quarterly_repository import QuarterlyRepository
from app.database import execute_query
from app.strategy.atr_chan import build_internal_adapter

router = APIRouter(prefix="/api/v1/backtest/parameters", tags=["atr-parameters"])


def _repo() -> QuarterlyRepository:
    return QuarterlyRepository()


@router.get("/current")
def current_parameter():
    row = _repo().current()
    return {"current": row}


@router.get("/history")
def parameter_history(limit: int = Query(50, ge=1, le=200)):
    return {"items": _repo().history(limit=limit)}


@router.get("/quarterly-report")
def quarterly_report(evaluation_quarter: str | None = None, run_id: str | None = None):
    return {"items": _repo().reports(evaluation_quarter=evaluation_quarter, run_id=run_id)}


@router.get("/{parameter_version}")
def parameter_version(parameter_version: str):
    row = _repo().version(parameter_version)
    if row is None:
        raise HTTPException(status_code=404, detail="parameter version not found")
    return row


@router.post("/quarterly-run")
def quarterly_run(payload: dict):
    required = ("evaluation_quarter", "data_as_of")
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise HTTPException(status_code=422, detail=f"missing fields: {', '.join(missing)}")
    repository = _repo()
    current_row = repository.current()
    current = ParameterState(
        atr_period=int((current_row or {}).get("atr_period", 14)),
        atr_exit_mult=float((current_row or {}).get("atr_exit_mult", payload.get("current_multiplier", 2.5))),
        parameter_version=(current_row or {}).get("parameter_version", "initial"),
        effective_date=str((current_row or {}).get("effective_date") or "") or None,
    )
    rows = execute_query("SELECT DISTINCT stock_code FROM trade_stock_status WHERE stock_code IS NOT NULL ORDER BY stock_code")
    stock_codes = [row["stock_code"] for row in rows]
    start = payload.get("start_date", "2022-01-01")
    data_by_stock = {}
    skipped_stocks = []
    for code in stock_codes:
        try:
            data_by_stock[code] = load_daily_bars(code, start, payload["data_as_of"], execute_query)
        except ValueError as exc:
            if str(exc) == "行情数据为空":
                skipped_stocks.append({"stock_code": code, "reason": str(exc)})
                continue
            raise
    if not data_by_stock:
        return {"status": "blocked", "reason": "data_incomplete", "missing": "all_stock_daily_bars", "stock_count": len(stock_codes), "skipped_stocks": skipped_stocks}
    result = QuarterlyParameterService(repository=repository, output_dir=payload.get("output_dir", "data/backtest/quarterly")).run(
        data_by_stock=data_by_stock, stock_codes=list(data_by_stock), current=current,
        evaluation_quarter=payload["evaluation_quarter"], data_as_of=payload["data_as_of"],
        candidates=payload.get("candidates"), range_start=payload.get("range_start"),
        range_end=payload.get("range_end"), step=payload.get("step"), baseline=bool(payload.get("baseline", False)),
        adapter=build_internal_adapter(),
    )
    return result
