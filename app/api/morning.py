"""晨会分析 API：缓存、历史报告和 SSE 工作流。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from app.config import settings
from app.services import morning_brief

router = APIRouter(prefix="/morning", tags=["晨会分析"])


def _event(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


@router.get("/cache", summary="读取最近一次晨会缓存")
def get_cache():
    data = morning_brief.load_latest()
    if not data:
        raise HTTPException(status_code=404, detail="暂无晨会缓存，请先运行晨会分析")
    return data


@router.get("/history", summary="查询晨会运行历史")
def get_history(limit: int = Query(20, ge=1, le=100)):
    data = morning_brief.list_history(limit)
    return {"data": data, "count": len(data)}


@router.get("/report", summary="读取晨报文件")
def get_report(path: str = Query(...), format: str = Query("html", pattern="^(html|markdown)$")):
    report_path = Path(path).expanduser().resolve()
    report_dir = morning_brief.REPORT_DIR.resolve()
    if report_dir not in report_path.parents or not report_path.is_file():
        raise HTTPException(status_code=404, detail="报告不存在或路径不受允许")
    if format == "markdown":
        return FileResponse(report_path, media_type="text/markdown; charset=utf-8")
    return FileResponse(report_path, media_type="text/html; charset=utf-8")


@router.get("/stream", summary="SSE 流式运行晨会")
async def stream_morning(
    top_industries: int = Query(3, ge=1, le=10),
    top_stocks: int = Query(5, ge=1, le=20),
    sample_per_industry: int = Query(15, ge=5, le=50),
    lookback: int = Query(90, ge=60, le=250),
    industry_level: int = Query(2, ge=1, le=2),
    enable_push: bool = Query(True),
):
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    params = {"top_industries": top_industries, "top_stocks": top_stocks, "sample_per_industry": sample_per_industry, "lookback": lookback, "industry_level": industry_level, "enable_push": enable_push}

    def emit(name: str, payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (name, payload))

    async def worker() -> None:
        try:
            result = await asyncio.to_thread(morning_brief.run, params, emit)
            await queue.put(("done", result))
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

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
