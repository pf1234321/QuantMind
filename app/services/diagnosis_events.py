"""个股诊断事件与催化剂分析。"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

import html
import re

from app.database import execute_query, execute_update

EVENT_RULES = {
    "业绩": ("fundamental", "positive", "medium"), "预增": ("fundamental", "positive", "medium"),
    "回购": ("capital", "positive", "short"), "增持": ("capital", "positive", "short"),
    "重组": ("corporate", "positive", "long"), "政策": ("policy", "positive", "medium"),
    
    "减持": ("capital", "negative", "short"), "处罚": ("regulatory", "negative", "medium"),
    "监管": ("regulatory", "negative", "medium"), "合同": ("business", "positive", "medium"),
    "风险": ("risk", "negative", "medium"), "解禁": ("capital", "negative", "short"),
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _normalize_text(value: Any) -> str:
    text = str(value or "")
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_datetime(value: Any) -> str:
    if not value:
        return ""
    try:
        return str(value)[:19].replace("T", " ")
    except:
        return str(value)[:19]


def _news_fingerprint(row: dict[str, Any]) -> str:
    stock_code = str(row.get("stock_code") or "").strip()
    published_at = _normalize_datetime(row.get("published_at"))
    title = _normalize_text(row.get("title") or row.get("news_title"))
    content = _normalize_text(row.get("content") or row.get("summary"))

    raw = "\x1f".join([stock_code, published_at, title, content])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event_fingerprint(news_fingerprint: str, event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "").strip()
    direction = str(event.get("impact_direction") or "").strip()
    event_key = str(event.get("event_key") or "").strip()
    key_variables = _json(event.get("key_variables") or [])

    raw = "\x1f".join([news_fingerprint, event_type, direction, event_key, key_variables])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def init_schema() -> None:
    execute_update("""CREATE TABLE IF NOT EXISTS diagnosis_event (
        event_id VARCHAR(64) PRIMARY KEY, diagnosis_id VARCHAR(64) NULL, stock_code VARCHAR(32) NOT NULL,
        event_type VARCHAR(64) NOT NULL, impact_direction VARCHAR(20) NOT NULL, impact_strength VARCHAR(20) NOT NULL,
        impact_horizon VARCHAR(20) NOT NULL, event_time DATETIME NULL, publish_time DATETIME NULL,
        title VARCHAR(512) NULL, summary TEXT NULL, key_variables JSON NULL, transmission_path JSON NULL,
        confidence DECIMAL(8,4) NULL, invalid_conditions JSON NULL, evidence_ids JSON NULL,
        input_fingerprint VARCHAR(128) NOT NULL, data_as_of DATE NULL, created_at DATETIME NOT NULL,
        news_fingerprint VARCHAR(128) NULL, event_fingerprint VARCHAR(128) NULL,
        extraction_method VARCHAR(20) NULL, extraction_status VARCHAR(20) NOT NULL DEFAULT 'completed',
        INDEX idx_diagnosis_event_stock (stock_code, data_as_of), INDEX idx_diagnosis_event_diagnosis (diagnosis_id),
        UNIQUE KEY uk_event_fingerprint (event_fingerprint)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    execute_update("""CREATE TABLE IF NOT EXISTS diagnosis_news_analysis (
        analysis_id VARCHAR(64) PRIMARY KEY,
        stock_code VARCHAR(32) NOT NULL,
        source_news_id VARCHAR(128) NULL,
        news_fingerprint VARCHAR(128) NOT NULL,
        diagnosis_id VARCHAR(64) NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'processing',
        extraction_method VARCHAR(20) NULL,
        error_message TEXT NULL,
        analyzed_at DATETIME NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_news_analysis (stock_code, news_fingerprint),
        INDEX idx_news_analysis_source (stock_code, source_news_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")


def _classify_rules(text: str) -> list[dict[str, Any]]:
    candidates = []
    for keyword, value in EVENT_RULES.items():
        if keyword in text:
            event_type, direction, horizon = value
            candidates.append({
                "event_type": event_type,
                "impact_direction": direction,
                "impact_horizon": horizon,
                "matched_keywords": [keyword]
            })
    return candidates


def classify_events_with_llm(title: str, content: str, rules: dict) -> list[dict[str, Any]]:
    # 使用阿里千问大模型
    from app.services.llm_client import call_qwen

    prompt = f"""你是一个专业的股票新闻事件识别专家。

事件规则：
{EVENT_RULES}

请判断下面新闻是否属于给定事件规则，并返回结构化JSON。

新闻标题：{title}
新闻正文：{content}

要求：
- 一条新闻可以识别出多个事件
- 只能使用上述 event_type
- 必须返回 "events" 数组
- 每个事件必须包含 event_type, impact_direction, impact_strength, impact_horizon, summary, key_variables, transmission_path, confidence
- confidence 必须在 0.6 到 1.0 之间
- 不要臆测金额、日期和公司行为

请直接返回 JSON，不要有任何其他文字。"""

    try:
        response = call_qwen(prompt)
        return response.get("events", [])
    except Exception:
        return []


def validate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = []
    for event in events:
        if not event.get("event_type") or not event.get("impact_direction"):
            continue
        if event.get("confidence", 0) < 0.6:
            continue
        valid.append(event)
    return valid


def detect_events(stock_code: str, data_as_of: str | None = None, diagnosis_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows = execute_query("SELECT * FROM trade_stock_news WHERE stock_code=%s ORDER BY published_at DESC LIMIT %s", (stock_code, limit))
    events: list[dict[str, Any]] = []

    for row in rows:
        published = str(row.get("published_at") or "")[:10]
        if data_as_of and published and published > data_as_of[:10]:
            continue

        title = _normalize_text(row.get("title") or row.get("news_title"))
        content = _normalize_text(row.get("content") or row.get("summary"))
        text = f"{title}\n{content}"

        news_fingerprint = _news_fingerprint(row)

        # 1. 检查新闻是否已分析
        existing = execute_query(
            "SELECT analysis_id, status FROM diagnosis_news_analysis "
            "WHERE stock_code=%s AND news_fingerprint=%s LIMIT 1",
            (stock_code, news_fingerprint)
        )
        if existing:
            status = existing[0].get("status")
            if status == "completed":
                # 读取历史事件
                history = execute_query(
                    "SELECT * FROM diagnosis_event WHERE news_fingerprint=%s ORDER BY created_at DESC",
                    (news_fingerprint,)
                )
                for h in history:
                    h["news_fingerprint"] = news_fingerprint
                    h["event_fingerprint"] = h.get("event_fingerprint")
                    events.append(h)
                continue
            elif status == "processing":
                continue

        # 2. 未处理，调用阿里千问大模型
        try:
            event_items = classify_events_with_llm(title, content, EVENT_RULES)
            event_items = validate_events(event_items)
            extraction_method = "llm"
        except Exception:
            event_items = _classify_rules(text)
            extraction_method = "rule"

        # 3. 逐条写入事件
        for index, item in enumerate(event_items):
            item["news_fingerprint"] = news_fingerprint
            item["event_fingerprint"] = _event_fingerprint(news_fingerprint, item)
            item["extraction_method"] = extraction_method

            event = {
                "event_id": str(uuid.uuid4()),
                "diagnosis_id": diagnosis_id,
                "stock_code": stock_code,
                "event_type": item["event_type"],
                "impact_direction": item["impact_direction"],
                "impact_strength": item.get("impact_strength", "medium"),
                "impact_horizon": item["impact_horizon"],
                "publish_time": published or None,
                "title": title,
                "summary": item.get("summary", content[:500]),
                "key_variables": item.get("key_variables", []),
                "transmission_path": item.get("transmission_path", []),
                "confidence": item.get("confidence", 0.65),
                "invalid_conditions": item.get("invalid_conditions", ["事件影响已被市场充分定价"]),
                "evidence_ids": [],
                "input_fingerprint": news_fingerprint,
                "news_fingerprint": news_fingerprint,
                "event_fingerprint": item["event_fingerprint"],
                "extraction_method": extraction_method,
                "data_as_of": data_as_of,
                "created_at": datetime.now()
            }

            # 插入事件
            execute_update(
                "INSERT INTO diagnosis_event (event_id,diagnosis_id,stock_code,event_type,impact_direction,impact_strength,impact_horizon,publish_time,title,summary,key_variables,transmission_path,confidence,invalid_conditions,evidence_ids,input_fingerprint,data_as_of,created_at,news_fingerprint,event_fingerprint,extraction_method) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                tuple(event.values())
            )

            events.append(event)

        # 4. 记录分析状态
        execute_update(
            "INSERT INTO diagnosis_news_analysis (analysis_id,stock_code,news_fingerprint,diagnosis_id,status,extraction_method,analyzed_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), stock_code, news_fingerprint, diagnosis_id, "completed", extraction_method, datetime.now())
        )

    return events


def list_events(diagnosis_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = execute_query("SELECT * FROM diagnosis_event WHERE diagnosis_id=%s ORDER BY publish_time DESC LIMIT %s", (diagnosis_id, limit))
    for row in rows:
        for key in ("key_variables", "transmission_path", "invalid_conditions", "evidence_ids"):
            if isinstance(row.get(key), str):
                try:
                    row[key] = json.loads(row[key])
                except json.JSONDecodeError:
                    pass
    return rows
