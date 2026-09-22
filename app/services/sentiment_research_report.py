# -*- coding: utf-8 -*-
"""个股舆情报告 + 宏观舆情简报生成。

个股报告（create_report）：
  - 收集 sentiment_detail / market_events / fear_index_history 中的证据
  - 入参 fingerprint（股票 + 天数 + 聚合分析时间）缓存，避免重复生成
  - 调用 LLM 拼接 4 段式 Prompt（情绪画像 → 主题事件 → 风险机会 → 结论建议）

宏观简报（run_macro_brief）：
  - 仿照 morning_brief.run 的 4 节点流式工作流
  - 节点顺序：aggregate → events → fear_index → report
  - emit('progress' / 'node_done' / 'done' / 'error_event')
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import threading
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.database import execute_many, execute_query, execute_update
from app.services.rag_analysis import _llm_chat

logger = logging.getLogger(__name__)

REPORT_VERSION = "sentiment-research-v1"
DISCLAIMER = "本舆情报告基于公开新闻与情绪聚合数据生成，仅供研究参考，不构成投资建议。"
MACRO_REPORT_DIR = settings.DATA_DIR / "reports" / "sentiment"
RUN_LOCK = threading.Lock()
NODE_ORDER = ["aggregate", "events", "fear_index", "report"]
NODE_LABELS = {
    "aggregate": "市场情绪聚合",
    "events": "主题事件抽取",
    "fear_index": "宏观恐慌指标",
    "report": "综合舆情报告",
}


def init_schema() -> None:
    """建表（幂等）。"""
    execute_update(
        """CREATE TABLE IF NOT EXISTS sentiment_research_report (
            report_id VARCHAR(64) NOT NULL PRIMARY KEY,
            stock_code VARCHAR(32) NOT NULL,
            report_version VARCHAR(32) NOT NULL,
            status VARCHAR(20) NOT NULL,
            data_as_of DATE NULL,
            input_fingerprint VARCHAR(128) NOT NULL,
            content_markdown LONGTEXT NULL,
            content_html LONGTEXT NULL,
            result_json JSON NULL,
            validation_json JSON NULL,
            model_name VARCHAR(128) NULL,
            prompt_version VARCHAR(64) NULL,
            algorithm_version VARCHAR(64) NULL,
            created_at DATETIME NOT NULL,
            finished_at DATETIME NULL,
            KEY idx_sentiment_report_stock (stock_code),
            KEY idx_sentiment_report_status (status, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    execute_update(
        """CREATE TABLE IF NOT EXISTS sentiment_research_evidence (
            evidence_id VARCHAR(64) NOT NULL PRIMARY KEY,
            report_id VARCHAR(64) NOT NULL,
            source_type VARCHAR(32) NOT NULL,
            source_id VARCHAR(128) NULL,
            title VARCHAR(512) NULL,
            source VARCHAR(255) NULL,
            publish_date DATE NULL,
            quote_text TEXT NULL,
            retrieval_method VARCHAR(64) NULL,
            relevance_score DECIMAL(10,6) NULL,
            data_as_of DATE NULL,
            lookahead_check VARCHAR(20) NOT NULL,
            created_at DATETIME NOT NULL,
            KEY idx_sentiment_evidence_report (report_id),
            KEY idx_sentiment_evidence_source (source_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )


# ================================================================ 通用工具
def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fingerprint(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(_json(snapshot).encode("utf-8")).hexdigest()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ================================================================ 个股报告
def _fetch_aggregate(stock_code: str, days: int) -> dict[str, Any] | None:
    rows = execute_query(
        "SELECT * FROM sentiment_aggregate WHERE stock_code=%s "
        "ORDER BY analyzed_at DESC LIMIT 1",
        (stock_code,),
    )
    return rows[0] if rows else None


def _fetch_recent_detail(stock_code: str, days: int, limit: int = 50) -> list[dict[str, Any]]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return execute_query(
        "SELECT stock_code, news_title, news_text, sentiment, strength, "
        "keywords, summary, market_impact, news_source, news_date, analyzed_at "
        "FROM sentiment_detail "
        "WHERE stock_code=%s AND news_date >= %s "
        "ORDER BY news_date DESC, strength DESC LIMIT %s",
        (stock_code, since, limit),
    )


def _fetch_recent_events(stock_code: str, days: int, limit: int = 30) -> list[dict[str, Any]]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return execute_query(
        "SELECT stock_code, event_type, event_subtype, event_desc, `signal`, news_date, created_at "
        "FROM market_events WHERE stock_code=%s AND news_date >= %s "
        "ORDER BY created_at DESC LIMIT %s",
        (stock_code, since, limit),
    )


def _collect_evidence(
    stock_code: str, days: int, report_id: str, data_as_of: str
) -> tuple[int, list[dict[str, Any]]]:
    """收集证据并写入 sentiment_research_evidence，返回 (写入数, 用于 prompt 的精简列表)。"""
    detail = _fetch_recent_detail(stock_code, days, limit=50)
    events = _fetch_recent_events(stock_code, days, limit=30)
    rows: list[tuple[Any, ...]] = []
    selected: list[dict[str, Any]] = []
    now = datetime.now()
    cutoff = str(data_as_of)

    for idx, d in enumerate(detail):
        publish_date = d.get("news_date")
        if publish_date and str(publish_date)[:10] > cutoff:
            continue
        quote = (d.get("news_text") or "")[:200]
        rows.append((
            str(uuid.uuid4()), report_id, "news", str(idx), d.get("news_title") or "",
            d.get("news_source") or "东方财富", publish_date, quote,
            "recent", d.get("strength") or 0, cutoff, "passed", now,
        ))
        if len(selected) < 10:
            selected.append({
                "type": "news",
                "title": d.get("news_title"),
                "sentiment": d.get("sentiment"),
                "strength": d.get("strength"),
                "summary": d.get("summary"),
                "news_date": str(publish_date) if publish_date else None,
            })

    for idx, e in enumerate(events):
        publish_date = e.get("news_date")
        if publish_date and str(publish_date)[:10] > cutoff:
            continue
        rows.append((
            str(uuid.uuid4()), report_id, "event", str(idx),
            f"{e.get('event_type') or ''}/{e.get('event_subtype') or ''}",
            "market_events", publish_date, e.get("event_desc") or "",
            "keyword", None, cutoff, "passed", now,
        ))
        if len(selected) < 20:
            selected.append({
                "type": "event",
                "event_type": e.get("event_type"),
                "event_subtype": e.get("event_subtype"),
                "signal": e.get("signal"),
                "description": e.get("event_desc"),
                "news_date": str(publish_date) if publish_date else None,
            })

    # 加上宏观恐慌指数作背景证据
    fear_rows = execute_query(
        "SELECT vix, ovx, gvz, us10y, composite_score, risk_level, suggestion, recorded_at "
        "FROM fear_index_history ORDER BY recorded_at DESC LIMIT 1"
    )
    if fear_rows:
        f = fear_rows[0]
        rows.append((
            str(uuid.uuid4()), report_id, "fear_index", "latest", "市场恐慌贪婪指数",
            "fear_index_history", f.get("recorded_at"), f.get("suggestion") or "",
            "snapshot", f.get("composite_score"), cutoff, "passed", now,
        ))

    if rows:
        execute_many(
            """INSERT INTO sentiment_research_evidence
                (evidence_id, report_id, source_type, source_id, title, source,
                 publish_date, quote_text, retrieval_method, relevance_score,
                 data_as_of, lookahead_check, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            rows,
        )
    return len(rows), selected


INDIVIDUAL_PROMPT = """你是一位严谨的 A 股投研分析师，正在基于公开新闻与情绪数据撰写个股舆情研报。

股票：{stock_code}
分析窗口：最近 {days} 天
数据截至：{data_as_of}

可用证据（已通过时间一致性校验，仅使用 publish_date <= data_as_of 的条目）：
{evidence_block}

宏观背景：
{macro_block}

请按以下结构输出一份 Markdown 报告（直接写 Markdown，不要包裹代码块）：

## 一、情绪画像
- 当前情绪方向（贪婪/中性/恐慌）及量化水平
- 近期正面 / 负面新闻比例与典型代表
- 恐惧贪婪指数与近 {days} 天趋势

## 二、主题事件
- 重大事件清单（事件类型、子类型、信号方向、影响解读）
- 是否出现"资产重组 / 业绩预增 / 监管处罚 / 减持"等关键主题
- 事件对短期情绪的可能传导路径

## 三、风险与机会
- 主要风险：负面新闻、政策风险、宏观情绪共振等
- 主要机会：正面催化、行业向好、情绪修复窗口等
- 建议关注的关键指标与跟踪点

## 四、结论建议
- 整体舆情结论（1 句话）
- 投资视角的启示（仅研究层面，不构成投资建议）
- 失效条件：哪些信号出现意味着结论需要重新评估

注意：
1. 引用证据时尽量用括号标注 [news_title|news_date] 或 [event_subtype|news_date]
2. 不要凭空捏造数据；没有数据时写"暂无相关证据"
3. 不要给出具体买入卖出价位或仓位
"""


def _format_individual_prompt(
    stock_code: str, days: int, data_as_of: str,
    evidence: list[dict[str, Any]], aggregate: dict[str, Any] | None,
    fear: dict[str, Any] | None,
) -> str:
    lines: list[str] = []
    if aggregate:
        themes = aggregate.get("top_themes")
        try:
            themes_text = ", ".join(json.loads(themes)) if isinstance(themes, str) else ", ".join(themes or [])
        except (TypeError, json.JSONDecodeError):
            themes_text = ""
        agg_lines = [
            f"- 恐惧贪婪指数：{aggregate.get('fear_greed_index')}（{aggregate.get('overall_sentiment')}）",
            f"- 正/负/中性新闻：{aggregate.get('positive_count')}/{aggregate.get('negative_count')}/{aggregate.get('neutral_count')}",
            f"- 主题词：{themes_text or '-'}",
            f"- 分析时间：{aggregate.get('analyzed_at')}",
            f"- 摘要：{aggregate.get('summary') or '-'}",
        ]
    else:
        agg_lines = ["- 暂无情绪聚合数据"]

    for ev in evidence:
        if ev["type"] == "news":
            lines.append(
                f"- [news] [{ev.get('news_date') or '-'}] {ev.get('sentiment') or '-'}/强度{ev.get('strength') or '-'}: "
                f"{ev.get('title') or '-'} | {ev.get('summary') or '-'}"
            )
        elif ev["type"] == "event":
            lines.append(
                f"- [event] [{ev.get('news_date') or '-'}] {ev.get('event_type') or '-'}/{ev.get('event_subtype') or '-'} "
                f"({ev.get('signal') or '-'}): {ev.get('description') or '-'}"
            )

    evidence_block = "\n".join(lines) or "(暂无证据)"
    aggregate_block = "\n".join(agg_lines)

    if fear:
        macro_block = (
            f"市场恐慌指数 {fear.get('composite_score')}（{fear.get('risk_level') or '-'}），"
            f"VIX {fear.get('vix')}、OVX {fear.get('ovx')}、GVZ {fear.get('gvz')}、"
            f"美债10Y {fear.get('us10y')}；建议：{fear.get('suggestion') or '-'}"
        )
    else:
        macro_block = "暂无最新恐慌指数数据。"

    return INDIVIDUAL_PROMPT.format(
        stock_code=stock_code,
        days=days,
        data_as_of=data_as_of,
        evidence_block=evidence_block,
        macro_block=f"{aggregate_block}\n\n{macro_block}",
    )


def _generate_markdown_html(markdown: str) -> str:
    """极简 Markdown -> HTML（仅处理 # ## 段落、列表与粗体；标题前后加 <h2>/<h3>）。"""
    parts: list[str] = []
    in_list = False
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not line:
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append("<br/>")
            continue
        if line.startswith("## "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("### "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.lstrip().startswith("- "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{html.escape(line.lstrip()[2:])}</li>")
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        parts.append("</ul>")
    return f"<article class='sentiment-report'>{''.join(parts)}</article>"


def create_report(stock_code: str, days: int = 7) -> dict[str, Any]:
    """个股舆情报告：fingerprint 缓存 + 证据采集 + LLM 生成。"""
    code = str(stock_code).strip().split(".")[0]
    days = max(1, min(int(days or 7), 30))
    aggregate = _fetch_aggregate(code, days)
    fingerprint = _fingerprint({
        "stock_code": code,
        "days": days,
        "analyzed_at": str(aggregate.get("analyzed_at")) if aggregate else None,
    })
    cached = execute_query(
        "SELECT * FROM sentiment_research_report WHERE stock_code=%s AND input_fingerprint=%s "
        "AND status='completed' ORDER BY created_at DESC LIMIT 1",
        (code, fingerprint),
    )
    if cached:
        decoded = _decode_report(cached[0])
        decoded["cache_hit"] = True
        return decoded

    report_id = str(uuid.uuid4())
    data_as_of = _today()
    now = datetime.now()
    execute_update(
        """INSERT INTO sentiment_research_report
            (report_id, stock_code, report_version, status, data_as_of,
             input_fingerprint, model_name, prompt_version, algorithm_version, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            report_id, code, REPORT_VERSION, "running", data_as_of, fingerprint,
            settings.LLM_MODEL, "individual-v1", REPORT_VERSION, now,
        ),
    )

    try:
        evidence_count, evidence = _collect_evidence(code, days, report_id, data_as_of)
        fear_rows = execute_query(
            "SELECT vix, ovx, gvz, us10y, composite_score, risk_level, suggestion, recorded_at "
            "FROM fear_index_history ORDER BY recorded_at DESC LIMIT 1"
        )
        fear = fear_rows[0] if fear_rows else None
        prompt = _format_individual_prompt(code, days, data_as_of, evidence, aggregate, fear)
        try:
            markdown_body = _llm_chat(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[舆情报告] LLM 调用失败，降级为规则摘要: %s", exc)
            markdown_body = _fallback_individual_markdown(code, days, aggregate, evidence, fear)

        markdown = (
            f"# {code} 舆情研究简报（最近 {days} 天 / 数据截至 {data_as_of}）\n\n"
            f"{markdown_body}\n\n---\n*{DISCLAIMER}*"
        )
        content_html = _generate_markdown_html(markdown)
        result = {
            "report_id": report_id,
            "stock_code": code,
            "data_as_of": data_as_of,
            "days": days,
            "aggregate": _public_aggregate(aggregate),
            "evidence_count": evidence_count,
            "disclaimer": DISCLAIMER,
        }
        validation = {
            "status": "passed",
            "checks": {"snapshot_identity": True, "evidence_present": evidence_count > 0},
            "data_as_of": data_as_of,
        }
        execute_update(
            """UPDATE sentiment_research_report SET status=%s, content_markdown=%s,
                content_html=%s, result_json=%s, validation_json=%s, finished_at=%s
                WHERE report_id=%s""",
            ("completed", markdown, content_html, _json(result), _json(validation),
             datetime.now(), report_id),
        )
        result["content_markdown"] = markdown
        result["content_html"] = content_html
        result["status"] = "completed"
        result["validation"] = validation
        result["cache_hit"] = False
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("[舆情报告] 生成失败: %s", exc)
        execute_update(
            "UPDATE sentiment_research_report SET status=%s, validation_json=%s, finished_at=%s WHERE report_id=%s",
            ("failed", _json({"status": "failed", "error": str(exc)}), datetime.now(), report_id),
        )
        raise


def _fallback_individual_markdown(
    stock_code: str, days: int, aggregate: dict[str, Any] | None,
    evidence: list[dict[str, Any]], fear: dict[str, Any] | None,
) -> str:
    """LLM 不可用时的规则化简报。"""
    if aggregate:
        fgi = aggregate.get("fear_greed_index")
        label = aggregate.get("overall_sentiment") or "中性"
        pos = aggregate.get("positive_count") or 0
        neg = aggregate.get("negative_count") or 0
        neu = aggregate.get("neutral_count") or 0
    else:
        fgi, label, pos, neg, neu = 50, "中性（无数据）", 0, 0, 0
    lines = [
        f"## 一、情绪画像",
        f"- 情绪方向：**{label}**（FGI={fgi}）",
        f"- 近 {days} 天新闻分布：正面 {pos} / 负面 {neg} / 中性 {neu}",
        f"- 当前情绪：{'偏贪婪' if fgi >= 60 else '偏恐慌' if fgi < 40 else '中性'}",
        "",
        f"## 二、主题事件",
    ]
    if evidence:
        for ev in evidence[:8]:
            if ev["type"] == "news":
                lines.append(f"- [新闻] {ev.get('title') or '-'}（{ev.get('sentiment') or '-'}/{ev.get('strength') or '-'}）")
            else:
                lines.append(f"- [事件] {ev.get('event_subtype') or ev.get('event_type') or '-'}：{ev.get('description') or '-'}")
    else:
        lines.append("- 暂无重大事件数据")
    lines.append("")
    lines.append("## 三、风险与机会")
    if fear:
        lines.append(f"- 宏观情绪：{fear.get('risk_level') or '-'}（{fear.get('composite_score')}），建议 {fear.get('suggestion') or '-'}")
    else:
        lines.append("- 暂无最新宏观恐慌指数")
    lines.append("- 主要跟踪指标：FGI、负面新闻数、宏观 VIX、行业政策事件")
    lines.append("")
    lines.append("## 四、结论建议")
    lines.append(f"- 当前个股舆情整体为 **{label}** 区间，建议持续跟踪重大事件与宏观指标。")
    return "\n".join(lines)


def _public_aggregate(agg: dict[str, Any] | None) -> dict[str, Any] | None:
    if not agg:
        return None
    return {
        "fear_greed_index": agg.get("fear_greed_index"),
        "overall_sentiment": agg.get("overall_sentiment"),
        "positive_count": agg.get("positive_count"),
        "negative_count": agg.get("negative_count"),
        "neutral_count": agg.get("neutral_count"),
        "news_count": agg.get("news_count"),
        "analyzed_at": agg.get("analyzed_at"),
        "summary": agg.get("summary"),
    }


def _decode_report(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "report_id": row.get("report_id"),
        "stock_code": row.get("stock_code"),
        "data_as_of": row.get("data_as_of"),
        "status": row.get("status"),
        "content_markdown": row.get("content_markdown"),
        "content_html": row.get("content_html"),
        "result_json": row.get("result_json"),
        "validation": row.get("validation_json"),
        "created_at": row.get("created_at"),
        "finished_at": row.get("finished_at"),
        "report_version": row.get("report_version"),
    }
    if isinstance(result["result_json"], str):
        try:
            result["result_json"] = json.loads(result["result_json"])
        except (TypeError, json.JSONDecodeError):
            result["result_json"] = {}
    return result


def get_report(stock_code: str, report_id: str | None = None) -> dict[str, Any] | None:
    sql = "SELECT * FROM sentiment_research_report WHERE stock_code=%s"
    params: list[Any] = [str(stock_code).strip()]
    if report_id:
        sql += " AND report_id=%s"
        params.append(report_id)
    sql += " ORDER BY created_at DESC LIMIT 1"
    rows = execute_query(sql, params)
    return _decode_report(rows[0]) if rows else None


def list_reports(stock_code: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    sql = "SELECT * FROM sentiment_research_report"
    params: list[Any] = []
    if stock_code:
        sql += " WHERE stock_code=%s"
        params.append(str(stock_code).strip())
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(int(limit))
    rows = execute_query(sql, params)
    return [_decode_report(r) for r in rows]


# ================================================================ 宏观舆情简报
def _macro_aggregate(days: int = 3) -> dict[str, Any]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = execute_query(
        "SELECT COUNT(*) AS stocks, SUM(news_count) AS news, "
        "ROUND(AVG(fear_greed_index)) AS avg_fgi "
        "FROM sentiment_aggregate WHERE analyzed_at >= %s",
        (since,),
    )
    if not rows:
        return {"stocks": 0, "news": 0, "avg_fgi": 50}
    r = rows[0]
    return {
        "stocks": int(r.get("stocks") or 0),
        "news": int(r.get("news") or 0),
        "avg_fgi": int(r.get("avg_fgi") or 50),
    }


def _macro_events(days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return execute_query(
        "SELECT stock_code, event_type, event_subtype, event_desc, `signal`, news_date "
        "FROM market_events WHERE news_date >= %s "
        "ORDER BY created_at DESC LIMIT %s",
        (since, limit),
    )


def _macro_fear() -> dict[str, Any] | None:
    rows = execute_query(
        "SELECT vix, ovx, gvz, us10y, composite_score, risk_level, suggestion, recorded_at "
        "FROM fear_index_history ORDER BY recorded_at DESC LIMIT 1"
    )
    return rows[0] if rows else None


def _build_macro_markdown(aggregate: dict[str, Any], events: list[dict[str, Any]], fear: dict[str, Any] | None) -> str:
    avg = aggregate.get("avg_fgi") or 50
    label = "贪婪" if avg >= 75 else "乐观" if avg >= 60 else "中性" if avg >= 40 else "谨慎" if avg >= 25 else "恐慌"
    lines = [
        f"# A 股舆情与宏观风险综合简报（数据截至 {datetime.now().strftime('%Y-%m-%d %H:%M')}）",
        "",
        f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 核心结论",
        f"市场整体情绪 **{label}**（聚合 FGI={avg}），覆盖 {aggregate.get('stocks', 0)} 只股票 / {aggregate.get('news', 0)} 条新闻；"
        f"近期 {'高度关注' if len(events) >= 10 else '事件数量适中'}。宏观层面{'需要警惕' if fear and fear.get('composite_score', 50) < 40 else '相对平稳'}。",
        "",
        "## 市场情绪聚合",
        f"- 平均恐惧贪婪指数：**{avg}**（{label}）",
        f"- 覆盖股票数：{aggregate.get('stocks', 0)}",
        f"- 累计新闻数：{aggregate.get('news', 0)}",
        "",
        "## 重大事件清单",
    ]
    if events:
        lines.append("| 股票 | 类型 | 子类型 | 信号 | 日期 |")
        lines.append("|---|---|---|---|---|")
        for e in events:
            lines.append(f"| {e.get('stock_code') or '-'} | {e.get('event_type') or '-'} | {e.get('event_subtype') or '-'} | {e.get('signal') or '-'} | {e.get('news_date') or '-'} |")
    else:
        lines.append("- 暂无重大事件")

    lines.append("")
    lines.append("## 宏观恐慌指标")
    if fear:
        lines.append(
            f"- 综合评分：**{fear.get('composite_score')}**（{fear.get('risk_level') or '-'}）"
            f" / VIX {fear.get('vix')} / OVX {fear.get('ovx')} / GVZ {fear.get('gvz')} / 美债10Y {fear.get('us10y')}"
        )
        lines.append(f"- 操作建议：{fear.get('suggestion') or '-'}")
    else:
        lines.append("- 暂无最新宏观数据")

    lines.append("")
    lines.append("## 盘中应对")
    lines.append("- 关注开盘 30 分钟情绪验证聚合 FGI 是否被放大或反向修正。")
    lines.append("- 高严重度事件优先复核公告与公司基本面，避免单纯根据舆情做出交易决策。")
    lines.append("- 宏观恐慌指标极端值出现时优先控制仓位，等待情绪企稳信号。")
    lines.append("")
    lines.append("---")
    lines.append(f"*{DISCLAIMER}*")
    return "\n".join(lines)


def _save_macro_report(markdown: str) -> tuple[str, str]:
    MACRO_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = MACRO_REPORT_DIR / f"sentiment_macro_{stamp}.md"
    html_path = MACRO_REPORT_DIR / f"sentiment_macro_{stamp}.html"
    md_path.write_text(markdown, encoding="utf-8")
    html_body = (
        "<!doctype html><html><meta charset='utf-8'><title>舆情宏观简报</title>"
        "<body><article class='sentiment-report'>" + "\n".join(
            f"<p>{html.escape(line)}</p>" if line and not line.startswith("|") and not line.startswith("#") else ""
            for line in markdown.splitlines()
        ) + "</article></body></html>"
    )
    html_path.write_text(html_body, encoding="utf-8")
    return str(md_path), str(html_path)


def run_macro_brief(
    params: dict[str, Any], emit: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """4 节点流式生成宏观舆情简报（仿 morning_brief.run）。"""
    if not RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("已有宏观舆情简报任务正在运行，请稍后重试")
    try:
        days_agg = int(params.get("days_aggregate", 3))
        days_events = int(params.get("days_events", 7))
        limit_events = int(params.get("limit_events", 20))
        state: dict[str, Any] = {"run_id": str(uuid.uuid4()), "params": params, "messages": []}

        def node(name: str, fn: Callable[[], None]) -> None:
            if emit:
                emit("progress", {
                    "current_node": name,
                    "node_index": NODE_ORDER.index(name) + 1,
                    "total_nodes": len(NODE_ORDER),
                    "message": f"正在执行：{NODE_LABELS[name]}",
                })
            fn()
            state["messages"].append(f"{NODE_LABELS[name]}完成")
            if emit:
                emit("node_done", {
                    "node": name,
                    "node_label": NODE_LABELS[name],
                    "state": {k: v for k, v in state.items() if k != "params"},
                })

        node("aggregate", lambda: state.update({"aggregate": _macro_aggregate(days=days_agg)}))
        node("events", lambda: state.update({"events": _macro_events(days=days_events, limit=limit_events)}))
        node("fear_index", lambda: state.update({"fear_index": _macro_fear()}))

        def _render() -> None:
            markdown = _build_macro_markdown(
                state.get("aggregate", {}),
                state.get("events", []),
                state.get("fear_index"),
            )
            md_path, html_path = _save_macro_report(markdown)
            state["report_markdown"] = markdown
            state["report_markdown_path"] = md_path
            state["report_html_path"] = html_path

        node("report", _render)
        state["data_as_of"] = (state.get("fear_index") or {}).get("recorded_at") or datetime.now().strftime("%Y-%m-%d")
        state["workflow_status"] = "completed"
        if emit:
            emit("done", {
                "run_id": state["run_id"],
                "data_as_of": state["data_as_of"],
                "report_markdown_path": state["report_markdown_path"],
                "report_html_path": state["report_html_path"],
                "aggregate": state["aggregate"],
                "events_count": len(state.get("events") or []),
                "fear_index": state["fear_index"],
            })
        return state
    except Exception as exc:  # noqa: BLE001
        logger.exception("sentiment_macro_run_failed")
        if emit:
            emit("error_event", {"message": str(exc), "status": "failed"})
        raise
    finally:
        RUN_LOCK.release()


# ================================================================ 兜底批处理
def _stock_name(code: str) -> str | None:
    rows = execute_query(
        "SELECT stock_name FROM trade_stock_status WHERE stock_code=%s LIMIT 1",
        (code,),
    )
    return rows[0]["stock_name"] if rows else None


def batch_generate_reports(group: str = "default", limit: int = 20, days: int = 7) -> dict[str, Any]:
    """从监控列表批量生成报告；用于 scheduler 兜底任务。"""
    from app.services.sentiment_watchlist import list_watch

    watches = list_watch(group=group, enabled_only=True)[: int(limit)]
    results: list[dict[str, Any]] = []
    success = 0
    for w in watches:
        code = w["stock_code"]
        try:
            data = create_report(code, days=days)
            results.append({"stock_code": code, "status": data.get("status", "completed"),
                            "cache_hit": data.get("cache_hit", False),
                            "report_id": data.get("report_id")})
            if data.get("status") == "completed":
                success += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[舆情报告批处理] %s 失败: %s", code, exc)
            results.append({"stock_code": code, "status": "failed", "error": str(exc)})
    return {"group": group, "total": len(watches), "success": success, "failed": len(watches) - success, "items": results}