"""个股诊断工作台 API。"""
from __future__ import annotations

import asyncio
import json
import os
import logging
from typing import AsyncIterator, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.stock_diagnosis import service
from app.services.diagnosis_research_report import create_report, get_report
from app.services.diagnosis_events import detect_events, list_events
from app.services.technical_backtest import ensure_kline_data_updated

router = APIRouter(prefix="/diagnoses", tags=["个股诊断"])
logger = logging.getLogger(__name__)


def _pdf_font() -> str | None:
    candidates = [
        os.getenv("REPORT_PDF_FONT"),
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf",
    ]
    return next((path for path in candidates if path and os.path.exists(path)), None)


def _pdf_value(value: object, depth: int = 0) -> str:
    if depth >= 3:
        return "..."
    if isinstance(value, dict):
        items = list(value.items())[:30]
        return "；".join(f"{key}: {_pdf_value(item, depth + 1)}" for key, item in items) or "-"
    if isinstance(value, (list, tuple)):
        items = list(value)[:10]
        return "；".join(_pdf_value(item, depth + 1) for item in items) or "-"
    if value is None:
        return "-"
    return str(value)


def _diagnosis_pdf(report: dict[str, object], diagnosis_id: str) -> bytes:
    import fitz  # type: ignore[import-not-found]

    font_path = _pdf_font()
    font_name = "helv"
    font_kwargs: dict[str, object] = {"fontname": font_name}
    font = fitz.Font(fontname=font_name)
    if font_path:
        font_kwargs = {"fontfile": font_path}
        font = fitz.Font(fontfile=font_path)

    page_width, page_height = fitz.paper_size("a4")
    margin = 42
    content_width = page_width - margin * 2
    document = fitz.open()
    page = document.new_page(width=page_width, height=page_height)
    y = margin

    def new_page() -> None:
        nonlocal page, y
        page = document.new_page(width=page_width, height=page_height)
        y = margin

    def ensure_space(height: float) -> None:
        nonlocal y
        if y + height > page_height - margin:
            new_page()

    def wrap_text(text: object, fontsize: float, width: float) -> list[str]:
        value = str(text if text not in (None, "") else "-")
        lines: list[str] = []
        current = ""
        for char in value:
            candidate = current + char
            if current and font.text_length(candidate, fontsize=fontsize) > width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current or not lines:
            lines.append(current)
        return lines

    def draw_text(text: object, x: float, top: float, width: float, fontsize: float = 10,
                  color: tuple[float, float, float] = (0.12, 0.18, 0.28)) -> float:
        lines = wrap_text(text, fontsize, width)
        line_height = fontsize * 1.55
        for line in lines:
            page.insert_text((x, top + fontsize), line, fontsize=fontsize, color=color, **font_kwargs)
            top += line_height
        return top

    def heading(text: str) -> None:
        nonlocal y
        ensure_space(38)
        page.draw_rect(fitz.Rect(margin, y, margin + content_width, y + 28), color=None, fill=(0.10, 0.22, 0.39))
        page.insert_text((margin + 10, y + 19), text, fontsize=12, color=(1, 1, 1), **font_kwargs)
        y += 38

    def key_value_table(section: dict[str, object]) -> None:
        nonlocal y
        label_width = 112
        value_width = content_width - label_width
        for key, value in list(section.items())[:40]:
            label = key
            value_text = _pdf_value(value)
            value_lines = wrap_text(value_text, 9, value_width - 16)
            for chunk_start in range(0, len(value_lines), 42):
                chunk = value_lines[chunk_start:chunk_start + 42]
                row_height = max(27, len(chunk) * 14 + 12)
                ensure_space(row_height + 2)
                page.draw_rect(fitz.Rect(margin, y, margin + label_width, y + row_height), color=(0.75, 0.81, 0.88), fill=(0.93, 0.96, 0.98))
                page.draw_rect(fitz.Rect(margin + label_width, y, margin + content_width, y + row_height), color=(0.82, 0.85, 0.89), fill=(1, 1, 1))
                draw_text(label if chunk_start == 0 else "", margin + 8, y + 5, label_width - 16, 9, (0.12, 0.22, 0.35))
                draw_text("".join(chunk), margin + label_width + 8, y + 5, value_width - 16, 9)
                y += row_height + 2

    title = str(report.get("stock_name") or "个股诊断报告")
    symbol = report.get("symbol", "-")
    page.insert_text((margin, y + 24), title, fontsize=21, color=(0.08, 0.20, 0.36), **font_kwargs)
    y += 40
    draw_text(f"股票代码：{symbol}    诊断编号：{diagnosis_id}", margin, y, content_width, 9, (0.35, 0.40, 0.48))
    y += 18
    draw_text(f"数据日期：{report.get('data_as_of') or '-'}    信号日期：{report.get('signal_date') or '-'}", margin, y, content_width, 9, (0.35, 0.40, 0.48))
    y += 28

    research = report.get("research")
    if isinstance(research, dict) and research.get("report"):
        heading("国泰君安五步法")
        markdown = str(research["report"])
        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if not line or line == "---":
                y += 6
                continue
            level = len(line) - len(line.lstrip("#"))
            if level:
                line = line[level:].strip()
                ensure_space(28)
                y = draw_text(line, margin, y, content_width, max(10, 14 - level), (0.08, 0.20, 0.36)) + 5
                continue
            if line.startswith(("- ", "* ", "+ ")):
                line = "• " + line[2:]
            line = line.replace("**", "").replace("__", "").replace("`", "")
            ensure_space(24)
            y = draw_text(line, margin, y, content_width, 9.5) + 3

        ensure_space(34)
        page.draw_line((margin, y), (margin + content_width, y), color=(0.78, 0.82, 0.88), width=0.7)
        y += 10
        draw_text("本报告由 AI 基于公告 RAG 自动生成，仅供研究参考，不构成投资建议。", margin, y, content_width, 8, (0.42, 0.46, 0.52))
        return document.tobytes()

    summary = report.get("summary")
    if isinstance(summary, dict):
        heading("综合结论")
        cards = [("综合评分", summary.get("score")), ("趋势", summary.get("trend")), ("置信度", summary.get("confidence"))]
        gap = 8
        card_width = (content_width - gap * 2) / 3
        ensure_space(60)
        for index, (label, value) in enumerate(cards):
            x = margin + index * (card_width + gap)
            page.draw_rect(fitz.Rect(x, y, x + card_width, y + 52), color=(0.73, 0.80, 0.89), fill=(0.94, 0.97, 1))
            page.insert_text((x + 10, y + 18), label, fontsize=9, color=(0.28, 0.36, 0.46), **font_kwargs)
            draw_text(value, x + 10, y + 24, card_width - 20, 14, (0.08, 0.20, 0.36))
        y += 66

    risk_reward = report.get("risk_reward")
    if isinstance(risk_reward, dict) and risk_reward:
        heading("定量风险收益")
        key_value_table(risk_reward)

    sections = report.get("sections")
    section_labels = {"market": "行情概览", "fundamental": "基本面分析", "technical": "技术面分析", "chan": "缠论信号", "factor": "因子分析", "risk": "风险提示"}
    if isinstance(sections, dict):
        for name, section in sections.items():
            heading(section_labels.get(name, name))
            if isinstance(section, dict):
                key_value_table(section)
            else:
                y = draw_text(_pdf_value(section), margin, y, content_width, 10)
                y += 8

    issues = report.get("errors")
    if isinstance(issues, dict) and issues:
        heading("诊断提示")
        key_value_table(issues)
    elif isinstance(issues, list) and issues:
        heading("诊断提示")
        for issue in issues:
            y = draw_text(issue, margin, y, content_width, 10)
            y += 5

    ensure_space(34)
    page.draw_line((margin, y), (margin + content_width, y), color=(0.78, 0.82, 0.88), width=0.7)
    y += 10
    draw_text(f"算法版本：{report.get('algorithm_version', '-')}    报告版本：{report.get('report_version', '-')}", margin, y, content_width, 8, (0.42, 0.46, 0.52))
    return document.tobytes()


class DiagnosisRequest(BaseModel):
    symbol: str = Field(..., min_length=1, description="股票代码，如 600519")
    periods: list[str] = Field(default_factory=lambda: ["DAILY", "WEEKLY"])
    modules: list[str] = Field(default_factory=lambda: ["market", "fundamental", "technical", "chan", "factor", "risk"])
    agent_types: list[str] | None = Field(default=None, description="可选 Agent：fundamental、technical、chan、factor、risk、sentiment")
    date_range: dict[str, str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    force_refresh: bool = False
    refresh_news: bool = Field(default=True, description="诊断前是否同步该股票最新新闻")
    risk_budget: float | None = Field(default=None, gt=0, lt=1)
    min_holding_days: int | None = Field(default=None, ge=1, le=365)
    max_holding_days: int | None = Field(default=None, ge=1, le=365)
    stop_mode: Literal["atr", "trailing_atr", "support"] = Field(default="atr")
    atr_period: int = Field(default=14, ge=2, le=60)
    atr_multiple: float | None = Field(default=None, gt=0, le=10)
    trailing_lookback: int = Field(default=20, ge=5, le=120)


@router.get("/stocks/search")
def search_stocks(q: str | None = Query(None, description="股票代码或名称"), limit: int = Query(20, ge=1, le=100)):
    data = service.search_stocks(q, limit)
    return {"data": data, "count": len(data)}


@router.get("/stocks/{symbol}/overview")
def stock_overview(symbol: str):
    result = service.overview(symbol)
    if not result:
        raise HTTPException(status_code=404, detail="股票不存在或没有可用数据")
    return result


@router.post("", status_code=202)
def create_diagnosis(request: DiagnosisRequest):
    try:
        # 在创建诊断前，确保K线数据是最新的
        stock_code = request.symbol
        logger.info(f"创建个股诊断前检查K线数据: {stock_code}")

        from datetime import date
        today = date.today().strftime('%Y%m%d')
        ensure_kline_data_updated(stock_code, today)

        return service.create(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"诊断任务创建失败: {exc}") from exc


@router.get("")
def list_diagnoses(symbol: str | None = Query(None), limit: int = Query(20, ge=1, le=100)):
    return {"data": service.list(symbol, limit)}


@router.get("/{diagnosis_id}/status")
def diagnosis_status(diagnosis_id: str):
    result = service.get(diagnosis_id)
    if not result:
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    return {"diagnosis_id": diagnosis_id, "status": result.get("status"), "progress": result.get("progress"),
            "current_stage": result.get("current_stage"), "stages": result.get("stage"), "error": result.get("error_message")}


@router.get("/{diagnosis_id}/report")
def diagnosis_report(diagnosis_id: str):
    result = service.get(diagnosis_id)
    if not result:
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    if not result.get("report"):
        raise HTTPException(status_code=409, detail="诊断报告尚未生成")
    report = result["report"]
    report["diagnosis_id"] = diagnosis_id
    return report


@router.post("/{diagnosis_id}/research-report", status_code=202)
def create_research_report(diagnosis_id: str):
    if not service.get(diagnosis_id):
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    try:
        return create_report(diagnosis_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"智能研报生成失败: {exc}") from exc


@router.get("/{diagnosis_id}/research-report")
def research_report(diagnosis_id: str, report_id: str | None = Query(None)):
    if not service.get(diagnosis_id):
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    result = get_report(diagnosis_id, report_id)
    if not result:
        raise HTTPException(status_code=404, detail="智能研报不存在")
    return result


@router.post("/{diagnosis_id}/event-analysis")
def create_diagnosis_events(diagnosis_id: str):
    task = service.get(diagnosis_id)
    if not task:
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    report = task.get("report") or {}
    stock_code = report.get("symbol") or task.get("stock_code")
    if not stock_code:
        raise HTTPException(status_code=422, detail="诊断缺少股票代码")
    return {"data": detect_events(str(stock_code), report.get("data_as_of"), diagnosis_id)}


@router.get("/{diagnosis_id}/event-analysis")
def get_diagnosis_events(diagnosis_id: str, limit: int = Query(100, ge=1, le=500)):
    if not service.get(diagnosis_id):
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    return {"data": list_events(diagnosis_id, limit)}


@router.get("/{diagnosis_id}/news-policy")
def diagnosis_news_policy(diagnosis_id: str):
    result = service.get(diagnosis_id)
    if not result:
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    report = result.get("report") or {}
    return report.get("sentiment") or {"status": "unavailable"}


@router.get("/{diagnosis_id}/risk-reward")
def diagnosis_risk_reward(diagnosis_id: str):
    if not service.get(diagnosis_id):
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    rows = service.quant_result(diagnosis_id, "risk_reward")
    return rows[0].get("result", rows[0]) if rows else {"status": "unavailable"}


@router.get("/{diagnosis_id}/industry-comparison")
def diagnosis_industry_comparison(diagnosis_id: str):
    if not service.get(diagnosis_id):
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    rows = service.quant_result(diagnosis_id, "industry_comparison")
    return rows[0].get("result", rows[0]) if rows else {"status": "unavailable"}


@router.get("/{diagnosis_id}/agents")
def diagnosis_agents(diagnosis_id: str):
    if not service.get(diagnosis_id):
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    return {"data": service.agent_results(diagnosis_id)}


@router.get("/{diagnosis_id}/debate")
def diagnosis_debate(diagnosis_id: str):
    if not service.get(diagnosis_id):
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    return service.debate(diagnosis_id) or {"status": "unavailable"}


@router.get("/{diagnosis_id}/consensus")
def diagnosis_consensus(diagnosis_id: str):
    if not service.get(diagnosis_id):
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    return service.consensus(diagnosis_id) or {"status": "unavailable"}


@router.get("/{diagnosis_id}/events")
async def diagnosis_events(diagnosis_id: str, offset: int = Query(0, ge=0)):
    if not service.get(diagnosis_id):
        raise HTTPException(status_code=404, detail="诊断任务不存在")

    async def stream() -> AsyncIterator[str]:
        cursor = offset
        idle = 0
        while idle < 120:
            events, cursor = service.events_since(diagnosis_id, cursor)
            if events:
                idle = 0
                for event in events:
                    yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            else:
                idle += 1
                yield ": heartbeat\n\n"
            result = service.get(diagnosis_id)
            if result and result.get("status") in {"completed", "partial", "failed", "cancelled", "expired"} and not events:
                break
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{diagnosis_id}/cancel")
def cancel_diagnosis(diagnosis_id: str):
    result = service.cancel(diagnosis_id)
    if not result:
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    return result


@router.post("/{diagnosis_id}/retry", status_code=202)
def retry_diagnosis(diagnosis_id: str):
    result = service.retry(diagnosis_id)
    if not result:
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    return result


@router.get("/{diagnosis_id}/export")
def export_diagnosis(diagnosis_id: str):
    result = service.get(diagnosis_id)
    if not result:
        raise HTTPException(status_code=404, detail="诊断任务不存在")
    if not result.get("report"):
        raise HTTPException(status_code=409, detail="诊断报告尚未生成")
    body = _diagnosis_pdf(result["report"], diagnosis_id)
    return StreamingResponse(iter([body]), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{diagnosis_id}.pdf"'})
