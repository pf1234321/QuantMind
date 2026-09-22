# -*- coding: utf-8 -*-
"""财经日历同步（akshare：百度财经日历）
迁移自: 02周 6-财经日历采集.py
表: trade_calendar_event
"""
import logging
from datetime import date, datetime, timedelta

import akshare as ak

from app.database import execute_many, execute_query

logger = logging.getLogger(__name__)

INSERT_SQL = """
INSERT INTO trade_calendar_event
(event_date, event_time, country, category, title, importance, previous_value,
 forecast_value, actual_value, impact, ai_prompt, source, source_url,
 is_recurring, recurrence_rule, status)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def sync_calendar(start_date: str | None = None, end_date: str | None = None) -> dict:
    """同步财经日历。默认最近 30 天。日期格式 YYYYMMDD"""
    today = datetime.now()
    s = datetime.strptime(start_date, "%Y%m%d") if start_date else today - timedelta(days=30)
    e = datetime.strptime(end_date, "%Y%m%d") if end_date else today + timedelta(days=7)

    total = 0
    failed = 0
    cur = s
    while cur <= e:
        date_str = cur.strftime("%Y-%m-%d")
        try:
            df = ak.news_economic_baidu(date=date_str.replace("-", ""))
            if df is not None and not df.empty:
                rows = []
                for _, r in df.iterrows():
                    time_val = str(r.get("时间", ""))
                    title = str(r.get("内容", ""))[:200]
                    country = str(r.get("地区", ""))
                    rows.append((
                        date_str, time_val, country, "other", title, 2,
                        None, None, None, None, None, "baidu", None,
                        None, None, "scheduled",
                    ))
                if rows:
                    execute_many(INSERT_SQL, rows)
                    total += len(rows)
        except Exception as ex:
            logger.warning("[日历] %s 失败: %s", date_str, ex)
            failed += 1
        cur += timedelta(days=1)

    today_date = date.today()
    coverage = execute_query(
        "SELECT MAX(event_date) AS latest_past FROM trade_calendar_event "
        "WHERE event_date <= %s",
        (today_date,),
    )
    future = execute_query(
        "SELECT MAX(event_date) AS latest_future FROM trade_calendar_event "
        "WHERE event_date > %s",
        (today_date,),
    )
    return {
        "source": "akshare", "written": total, "failed": failed,
        "range": [s.strftime("%Y%m%d"), e.strftime("%Y%m%d")],
        "latest_past_event_date": coverage[0]["latest_past"] if coverage else None,
        "latest_future_event_date": future[0]["latest_future"] if future else None,
    }
