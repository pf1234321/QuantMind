# -*- coding: utf-8 -*-
"""新闻事件同步（akshare）。"""
import logging
import time

import akshare as ak

from app.database import execute_query, execute_update

logger = logging.getLogger(__name__)

FIND_SQL = """
SELECT id FROM trade_stock_news
WHERE stock_code=%s AND title=%s AND published_at <=> %s
LIMIT 1
"""

INSERT_SQL = """
INSERT INTO trade_stock_news
(stock_code, news_type, title, content, source, source_url, published_at)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""

UPDATE_SQL = """
UPDATE trade_stock_news
SET content=%s, source=%s, source_url=%s
WHERE id=%s
"""

REQUIRED_COLUMNS = {"发布时间", "新闻标题"}


def sync_news(stock_codes: list[tuple[str, str]], limit_per_stock: int = 50,
              request_interval: float = 0.2, retries: int = 2) -> dict:
    """同步个股新闻，区分空数据、接口失败和实际写入。

    参数说明：
        stock_codes: 待同步股票列表，每项为 (股票代码, 股票名称)，例如
            [("600519", "贵州茅台")]。
        limit_per_stock: 每只股票最多获取并写入的新闻条数，默认 50 条。
        request_interval: 请求之间的等待间隔，单位为秒，默认 0.2 秒，
            用于降低请求过于频繁触发数据源限制的风险。
        retries: 单只股票请求失败后的重试次数，默认重试 2 次；加上首次请求，
            最多请求 retries + 1 次。
    """
    total = 0
    failed = 0
    empty = 0
    for code_num, name in stock_codes:
        for attempt in range(retries + 1):
            try:
                df = ak.stock_news_em(symbol=code_num)
                if df is None or df.empty:
                    empty += 1
                    break
                missing = REQUIRED_COLUMNS.difference(df.columns)
                if missing:
                    raise ValueError(f"新闻接口字段缺失: {sorted(missing)}，实际字段: {list(df.columns)}")
                rows = []
                for _, r in df.head(limit_per_stock).iterrows():
                    title = str(r.get("新闻标题", "")).strip()
                    if not title:
                        continue
                    news_time = r.get("发布时间")
                    rows.append((
                        code_num, "news", title,
                        str(r.get("新闻内容", "") or ""),
                        str(r.get("文章来源", "") or ""),
                        str(r.get("新闻链接", "") or ""),
                        str(news_time) if news_time else None,
                    ))
                if rows:
                    for row in rows:
                        existing = execute_query(FIND_SQL, (row[0], row[2], row[6]))
                        if existing:
                            execute_update(UPDATE_SQL, (row[3], row[4], row[5], existing[0]["id"]))
                        else:
                            execute_update(INSERT_SQL, row)
                        total += 1
                else:
                    empty += 1
                break
            except Exception as e:
                # AkShare 空响应时内部可能错误访问不存在的 code 列，按无数据处理。
                if isinstance(e, KeyError) and e.args == ("code",):
                    empty += 1
                    break
                if attempt >= retries:
                    logger.exception("[新闻] %s(%s) 失败: %s", name, code_num, e)
                    failed += 1
                else:
                    time.sleep(request_interval * (attempt + 1))
        time.sleep(request_interval)
    return {
        "source": "akshare", "written": total, "failed": failed,
        "empty": empty, "stocks": len(stock_codes),
    }
