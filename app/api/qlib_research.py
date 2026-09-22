"""Qlib 因子研究任务接口。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.qlib_research import POOL_BENCHMARKS, POOL_LABELS, service
from app.services.qlib_time_split import RESEARCH_START, RESEARCH_END, service as time_split_service

router = APIRouter(prefix="/qlib/research", tags=["Qlib 因子研究"])


class PoolValidationRequest(BaseModel):
    pool_type: str = Field(default="custom")
    stock_codes: list[str] | str | None = None


class RunRequest(PoolValidationRequest):
    name: str | None = None
    benchmark: str = Field(default="", description="回测基准指数代码；系统股票池由股票池自动决定")
    rebalance_frequency: str = Field(default="monthly", description="调仓频率：daily/weekly/monthly")
    prediction_target: str = Field(default="future_5d_return", description="预测目标")
    model_params: dict[str, object] = Field(default_factory=dict)
    start_date: str | None = None
    end_date: str | None = None


@router.get("/time-split")
def time_split():
    return time_split_service.build_snapshot([]).to_dict()


@router.get("/pools")
def pool_options():
    return {
        "data": [
            {
                "value": key,
                "label": label,
                "benchmark": POOL_BENCHMARKS.get(key),
            }
            for key, label in POOL_LABELS.items()
        ]
    }


@router.post("/pools/validate")
def validate_pool(request: PoolValidationRequest):
    try:
        return service.validate_pool(request.pool_type, request.stock_codes if isinstance(request.stock_codes, list) else [request.stock_codes] if request.stock_codes else [], RESEARCH_START, RESEARCH_END)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"股票池校验失败: {exc}") from exc


@router.post("/runs", status_code=202)
def create_run(request: RunRequest):
    try:
        return service.create_run(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"研究任务创建失败: {exc}") from exc


@router.get("/runs")
def list_runs(limit: int = Query(20, ge=1, le=100)):
    try:
        return {"data": service.list_runs(limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"研究任务列表查询失败: {exc}") from exc


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    result = service.get_run(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    return result


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    result = service.cancel(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    return result


@router.get("/runs/{run_id}/predictions")
def get_predictions(run_id: str, stage: str | None = None, trade_date: str | None = None, top_k: int = Query(20, ge=1, le=500)):
    if not service.get_run(run_id):
        raise HTTPException(status_code=404, detail="研究任务不存在")
    return {"data": service.get_predictions(run_id, stage, trade_date, top_k)}


@router.get("/runs/{run_id}/logs")
def get_logs(run_id: str):
    if not service.get_run(run_id):
        raise HTTPException(status_code=404, detail="研究任务不存在")
    return {"data": service.get_logs(run_id)}
