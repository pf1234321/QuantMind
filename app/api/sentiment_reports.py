# -*- coding: utf-8 -*-
"""舆情报告 API（个股异步 + 宏观 SSE + 落盘报告）"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from app.services import sentiment_research_report as svc
from app.services.sentiment_research_report import MACRO_REPORT_DIR

router = APIRouter(prefix="/sentiment-reports", tags=["舆情报告"])


def _event(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


@router.post("/{stock_code}", summary="触发个股舆情报告（异步指纹缓存）")
def create_report(stock_code: str, days: int = Query(7, ge=1, le=30)):
    try:
        result = svc.create_report(stock_code, days=days)
        return {
            "report_id": result.get("report_id"),
            "stock_code": result.get("stock_code"),
            "status": result.get("status"),
            "cache_hit": result.get("cache_hit", False),
            "data_as_of": result.get("data_as_of"),
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{stock_code}", summary="查询个股最新报告（命中 fingerprint 缓存）")
def get_report(stock_code: str):
    data = svc.get_report(stock_code)
    if not data:
        raise HTTPException(404, "暂无舆情报告，请先调用 POST 生成")
    return data


@router.get("/{stock_code}/history", summary="个股报告历史列表")
def list_reports(stock_code: str, limit: int = Query(20, ge=1, le=100)):
    items = svc.list_reports(stock_code=stock_code, limit=limit)
    return {"count": len(items), "data": items}


@router.get("/{stock_code}/{report_id}", summary="查询个股指定报告")
def get_specific_report(stock_code: str, report_id: str):
    data = svc.get_report(stock_code, report_id=report_id)
    if not data:
        raise HTTPException(404, "报告不存在")
    return data


@router.get("/stream", summary="SSE 流式运行宏观舆情简报")
async def stream_macro(
    days_aggregate: int = Query(3, ge=1, le=30),
    days_events: int = Query(7, ge=1, le=30),
    limit_events: int = Query(20, ge=1, le=100),
):
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    params = {
        "days_aggregate": days_aggregate,
        "days_events": days_events,
        "limit_events": limit_events,
    }

    def emit(name: str, payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (name, payload))

    async def worker() -> None:
        try:
            result = await asyncio.to_thread(svc.run_macro_brief, params, emit)
            await queue.put(("done", {
                "run_id": result.get("run_id"),
                "data_as_of": result.get("data_as_of"),
                "report_markdown_path": result.get("report_markdown_path"),
                "report_html_path": result.get("report_html_path"),
            }))
        except Exception as exc:
            await queue.put(("error_event", {"message": str(exc), "status": "failed"}))
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(worker())
        try:
            yield _event("connected", {"status": "running", "total_nodes": 4})
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if item is None:
                    break
                yield _event(item[0], item[1])
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/report", summary="读取宏观舆情简报文件")
def get_macro_report(path: str = Query(...), format: str = Query("html", pattern="^(html|markdown)$")):
    report_path = Path(path).expanduser().resolve()
    base_dir = MACRO_REPORT_DIR.resolve()
    if base_dir not in report_path.parents or not report_path.is_file():
        raise HTTPException(404, "报告不存在或路径不受允许")
    if format == "markdown":
        return FileResponse(report_path, media_type="text/markdown; charset=utf-8")
    return FileResponse(report_path, media_type="text/html; charset=utf-8")