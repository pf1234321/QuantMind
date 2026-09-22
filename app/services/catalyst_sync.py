# -*- coding: utf-8 -*-
"""关键催化剂事件同步（Qwen Max 联网搜索）
迁移自: 02周 7-关键催化剂采集.py
表: trade_calendar_event (source=qwen_search, importance>=2)
需要环境变量: DASHSCOPE_API_KEY
"""
import json
import logging
import os
from datetime import datetime, timedelta

from app.database import execute_many, execute_query

logger = logging.getLogger(__name__)

CATALYST_INSERT_SQL = """
INSERT INTO trade_calendar_event
(event_date, event_time, title, country, category, importance, source, ai_prompt)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
importance = GREATEST(importance, VALUES(importance)),
category = VALUES(category),
ai_prompt = COALESCE(VALUES(ai_prompt), ai_prompt)
"""

SEARCH_PROMPT_TEMPLATE = """请联网搜索 {start_date} 至 {end_date} 期间，对 A 股市场有重大影响的催化剂事件。
包括但不限于：重要会议（两会/政治局会议/中央经济工作会议）、美联储议息会议(FOMC)、
美国非农就业数据、CPI 数据、国内重要经济数据发布、产业政策发布、监管新规等。

请严格输出 JSON 数组，每个元素格式：
{{"date": "YYYY-MM-DD", "title": "事件名称", "country": "中国/美国/其他", "category": "policy/economic/data/other", "importance": 2 或 3}}

只输出 JSON，不要输出其他内容。"""


def _call_qwen(prompt: str, enable_search: bool = False) -> str:
    from openai import OpenAI

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("缺少环境变量 DASHSCOPE_API_KEY")
    client = OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    extra = {}
    if enable_search:
        extra = {"enable_search": True, "search_options": {"forced_search": True}}
    completion = client.chat.completions.create(
        model=os.getenv("QWEN_MODEL", "qwen-max"),
        messages=[{"role": "user", "content": prompt}],
        extra_body=extra,
    )
    return completion.choices[0].message.content.strip()


def _parse_json_array(content: str) -> list:
    start, end = content.find("["), content.rfind("]")
    if start == -1 or end == -1:
        return []
    return json.loads(content[start:end + 1])


def search_catalysts() -> list[dict]:
    """调用 Qwen Max 联网搜索未来 180 天催化剂"""
    today = datetime.now().date()
    prompt = SEARCH_PROMPT_TEMPLATE.format(
        start_date=today.isoformat(),
        end_date=(today + timedelta(days=180)).isoformat(),
    )
    logger.info("[催化剂] 调用 Qwen Max 联网搜索 ...")
    content = _call_qwen(prompt, enable_search=True)
    events = _parse_json_array(content)
    logger.info("[催化剂] 解析到 %d 个事件", len(events))
    return events


def save_events(events: list[dict]) -> int:
    """写入 trade_calendar_event（按标题+日期 5 天内去重）"""
    existing = execute_query(
        "SELECT id, event_date, title FROM trade_calendar_event WHERE source='qwen_search'"
    )
    existing_map: dict[str, list] = {}
    for row in existing:
        key = str(row["title"]).replace("/", "").replace(" ", "")
        existing_map.setdefault(key, []).append(row)

    rows = []
    for evt in events:
        date_str = str(evt.get("date", ""))
        title = str(evt.get("title", "")).strip()
        if not date_str or not title:
            continue
        try:
            evt_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        norm_title = title.replace("/", "").replace(" ", "")
        skip = False
        for ex in existing_map.get(norm_title, []):
            diff = abs((evt_date - ex["event_date"]).days)
            if diff <= 5:
                skip = True
                break
        if skip:
            continue

        importance = max(2, min(3, int(evt.get("importance", 2))))
        rows.append((
            date_str, None, title,
            str(evt.get("country", "中国")),
            str(evt.get("category", "policy")),
            importance, "qwen_search", None,
        ))

    if rows:
        execute_many(CATALYST_INSERT_SQL, rows)
    logger.info("[催化剂] 写入 %d 条", len(rows))
    return len(rows)


def sync_catalyst() -> dict:
    """催化剂同步主入口"""
    events = search_catalysts()
    if not events:
        return {"source": "qwen", "written": 0, "events": 0}
    written = save_events(events)
    return {"source": "qwen", "written": written, "events": len(events)}
