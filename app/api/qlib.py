"""Qlib 数据源和 trade_stock_daily 适配接口。"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.qlib_data_adapter import adapter
from app.services.qlib_data_sync import service as data_sync_service

router = APIRouter(prefix="/qlib", tags=["Qlib 数据"])


class ValidateRequest(BaseModel):
    stock_codes: list[str] | None = Field(default=None, description="股票代码列表；为空表示全市场")
    start_date: str | None = Field(default=None, description="开始日期，YYYY-MM-DD")
    end_date: str | None = Field(default=None, description="结束日期，YYYY-MM-DD")


def _codes(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item for item in re.split(r"[\s,，]+", value.strip()) if item]


def _run(func, *args, **kwargs):
    try:
        return func(*args, **kwargs).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Qlib 数据源不可用: {exc}") from exc


@router.get("/data-source/status", summary="查询 Qlib 数据源状态")
def data_source_status():
    """返回本地 Qlib 目录最后日期、Release 版本和同步状态。"""
    return data_sync_service.status()


@router.post("/data-source/sync", status_code=202, summary="同步最新 Qlib 数据")
def sync_data_source(force: bool = Query(False, description="是否强制重新下载当前远程快照")):
    return data_sync_service.start(force=force, sync_mode="force" if force else "manual")


@router.get("/data-source/sync/{sync_run_id}", summary="查询 Qlib 同步任务")
def get_data_sync_run(sync_run_id: str):
    result = data_sync_service.get_run(sync_run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Qlib同步任务不存在")
    return result


@router.get("/data-source/sync/{sync_run_id}/logs", summary="查询 Qlib 同步日志")
def get_data_sync_logs(sync_run_id: str):
    if not data_sync_service.get_run(sync_run_id):
        raise HTTPException(status_code=404, detail="Qlib同步任务不存在")
    return {"data": data_sync_service.get_logs(sync_run_id)}


@router.get("/data-source/coverage", summary="查询指定范围数据覆盖")
def data_source_coverage(
    start_date: str | None = Query(None, description="开始日期，YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期，YYYY-MM-DD"),
    stock_codes: str | None = Query(None, description="逗号分隔股票代码，例如 000001,600000"),
):
    return _run(adapter.get_coverage, _codes(stock_codes), start_date, end_date)


@router.post("/data-source/validate", summary="校验 Qlib 研究数据")
def data_source_validate(request: ValidateRequest):
    """校验股票池和日期范围是否满足 Alpha158 输入要求。"""
    report = _run(adapter.validate_data, request.stock_codes, request.start_date, request.end_date)
    blocked = report.get("status") == "blocked"
    return {
        **report,
        "allowed": not blocked,
        "requires_confirmation": report.get("status") == "warning",
        "blocking_reasons": [issue["message"] for issue in report.get("issues", []) if issue.get("blocked")],
    }


@router.get("/data-source/records", summary="读取 Qlib 标准行情记录")
def data_source_records(
    start_date: str | None = Query(None, description="开始日期，YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期，YYYY-MM-DD"),
    stock_codes: str | None = Query(None, description="逗号分隔股票代码"),
    limit: int = Query(1000, ge=1, le=10000, description="最多返回记录数"),
):
    """返回适配后的 Qlib 标准字段，供调试和小样本集成验证使用。"""
    try:
        records = adapter.get_qlib_records(_codes(stock_codes), start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Qlib 数据源不可用: {exc}") from exc
    return {"count": min(len(records), limit), "data": records[:limit]}
