"""诊断消息、舆情、政策和 RAG 证据聚合。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.database import execute_query

VERSION = "news-policy-v1"


def _date(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:10]


def _evidence(row: dict[str, Any], data_as_of: str | None, source: str) -> dict[str, Any]:
    published = _date(row.get("published_at") or row.get("ann_date") or row.get("news_date"))
    lookahead = bool(data_as_of and published and published > data_as_of)
    return {
        "source": source, "title": row.get("title") or row.get("news_title") or row.get("ann_title"),
        "published_at": published, "fetched_at": _date(row.get("fetched_at") or row.get("created_at")),
        "document_id": row.get("document_id") or row.get("id"), "quote": row.get("summary") or row.get("content") or row.get("news_text") or row.get("chunk"),
        "source_url": row.get("source_url"),
        "data_as_of": data_as_of, "lookahead_risk": lookahead,
    }


def build_news_policy_snapshot(stock_code: str, data_as_of: str | None, days: int = 30) -> dict[str, Any]:
    """基于已同步的新闻和情绪表构造快照；截止日之后内容永不进入摘要。"""
    code = str(stock_code)
    end = data_as_of or datetime.now().strftime("%Y-%m-%d")
    try:
        end_date = datetime.strptime(end, "%Y-%m-%d")
        start = (end_date - timedelta(days=days)).strftime("%Y-%m-%d")
    except ValueError:
        start = end[:7] + "-01" if len(end) >= 7 else end
    news = execute_query(
        "SELECT id, stock_code, title, content, summary, published_at, source, source_url, created_at, sentiment, sentiment_score FROM trade_stock_news WHERE stock_code=%s AND published_at<=%s AND published_at>=%s ORDER BY published_at DESC LIMIT %s",
        (code, end, start, days * 10),
    )
    evidence = [_evidence(row, data_as_of, row.get("source") or "trade_stock_news") for row in news]
    valid = [item for item in evidence if not item["lookahead_risk"]]
    positive = sum(1 for row in news if row.get("sentiment") == "positive")
    negative = sum(1 for row in news if row.get("sentiment") == "negative")
    neutral = sum(1 for row in news if row.get("sentiment") not in ("positive", "negative"))
    direction = "positive" if positive > negative else "negative" if negative > positive else "neutral"
    return {
        "status": "completed" if valid else "partial", "stock_code": code, "data_as_of": data_as_of,
        "summary": {"direction": direction, "strength": round(abs(positive - negative) / max(len(news), 1), 4), "event_type": "news", "impact_horizon": "short_term", "disagreement": min(1, min(positive, negative) / max(len(news), 1))},
        "sentiment": {"positive": positive, "negative": negative, "neutral": neutral, "count": len(news)},
        "policy": {"status": "待确认", "company_impact": None, "industry_impact": None, "supply_chain_impact": None, "earnings_assumption_impact": None},
        "evidence": valid, "quality_checks": {"evidence_count": len(valid), "lookahead_excluded": len(evidence) - len(valid)},
        "model_name": "rule-adapter", "prompt_version": VERSION, "algorithm_version": VERSION,
        "confidence": round(min(1, len(valid) / 20), 2), "disclaimer": "消息、政策和舆情分析仅供研究辅助，不构成投资建议。",
    }
