#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库写入模块 — 将舆情分析结果写入 MySQL。

用法：
    from db_writer import SentimentDB

    db = SentimentDB()
    db.save_detail(analyses, stock_code="002594")
    db.save_aggregate(aggregate, stock_code="002594")
    db.close()
"""

import json
import os
import sys
from datetime import datetime, date
from typing import Dict, List, Optional

import pymysql


class SentimentDB:
    """舆情分析数据库操作"""

    def __init__(self):
        # 优先从环境变量读取，否则使用默认配置
        self.host = os.getenv("DB_HOST", "localhost")
        self.port = int(os.getenv("DB_PORT", "3309"))
        self.user = os.getenv("DB_USER", "root")
        self.password = os.getenv("DB_PASSWORD", "root")
        self.database = os.getenv("DB_NAME", "wucai_trade")
        self._conn = None

    def connect(self):
        """建立数据库连接"""
        if self._conn is None or not self._conn.open:
            self._conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset="utf8mb4",
                autocommit=False,
            )
        return self._conn

    def close(self):
        """关闭连接"""
        if self._conn and self._conn.open:
            self._conn.close()
            self._conn = None

    def ensure_tables(self):
        """自动建表（如不存在）"""
        conn = self.connect()
        with open(
            os.path.join(os.path.dirname(__file__), "sentiment_tables.sql"),
            "r", encoding="utf-8",
        ) as f:
            sql = f.read()
        # 拆分多条语句执行
        for statement in sql.split(";"):
            s = statement.strip()
            if s and not s.startswith("--"):
                with conn.cursor() as cur:
                    cur.execute(s)
        conn.commit()
        print("[DB] 表结构已就绪")

    def save_detail(
        self,
        analyses: List[dict],
        stock_code: str,
        news_date: Optional[date] = None,
        news_source: Optional[str] = None,
    ) -> int:
        """
        批量写入逐条情感分析明细。

        Args:
            analyses: 情感分析结果列表
            stock_code: 股票代码
            news_date: 新闻日期（默认今天）
            news_source: 新闻来源

        Returns:
            写入条数
        """
        conn = self.connect()
        if news_date is None:
            news_date = date.today()

        sql = """
            INSERT INTO sentiment_detail
                (stock_code, news_title, news_text, sentiment, strength,
                 entities, keywords, summary, market_impact, news_source, news_date)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        rows = []
        for a in analyses:
            # 如果标题为空，使用正文前50字作为标题
            title = a.get("news_title", "").strip()
            if not title or title == "[]":
                text = a.get("news_text_preview", "")
                title = text[:50] + "..." if len(text) > 50 else text

            # 如果来源为空，设置默认值
            source = news_source or a.get("news_source", "").strip() or "未知来源"

            rows.append((
                stock_code,
                title,
                a.get("news_text_preview", ""),
                a.get("sentiment", "中性"),
                a.get("strength", 1),
                json.dumps(a.get("entities", []), ensure_ascii=False),
                json.dumps(a.get("keywords", []), ensure_ascii=False),
                a.get("summary", ""),
                a.get("market_impact", ""),
                source,
                news_date,
            ))

        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()

        print(f"[DB] 写入 {len(rows)} 条情感明细 (stock={stock_code})")
        return len(rows)

    def save_aggregate(self, aggregate: dict, stock_code: str) -> int:
        """
        写入聚合情绪指数。

        Args:
            aggregate: 聚合分析结果
            stock_code: 股票代码

        Returns:
            影响行数
        """
        conn = self.connect()

        sql = """
            INSERT INTO sentiment_aggregate
                (stock_code, fear_greed_index, overall_sentiment,
                 positive_count, negative_count, neutral_count,
                 top_themes, risk_alerts, opportunity_hints, summary, news_count)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                fear_greed_index   = VALUES(fear_greed_index),
                overall_sentiment  = VALUES(overall_sentiment),
                positive_count     = VALUES(positive_count),
                negative_count     = VALUES(negative_count),
                neutral_count      = VALUES(neutral_count),
                top_themes         = VALUES(top_themes),
                risk_alerts        = VALUES(risk_alerts),
                opportunity_hints  = VALUES(opportunity_hints),
                summary            = VALUES(summary),
                news_count         = VALUES(news_count)
        """
        with conn.cursor() as cur:
            cur.execute(sql, (
                stock_code,
                aggregate.get("fear_greed_index", 50),
                aggregate.get("overall_sentiment", "中性"),
                aggregate.get("positive_count", 0),
                aggregate.get("negative_count", 0),
                aggregate.get("neutral_count", 0),
                json.dumps(aggregate.get("top_themes", []), ensure_ascii=False),
                json.dumps(aggregate.get("risk_alerts", []), ensure_ascii=False),
                json.dumps(aggregate.get("opportunity_hints", []), ensure_ascii=False),
                aggregate.get("summary", ""),
                len(aggregate.get("positive_count", 0)
                    + aggregate.get("negative_count", 0)
                    + aggregate.get("neutral_count", 0))
                if not aggregate.get("fallback") else 0,
            ))
        conn.commit()

        print(f"[DB] 写入聚合情绪指数 (stock={stock_code}, FGI={aggregate.get('fear_greed_index', 'N/A')})")
        return cur.rowcount

    def save_event(self, events: List[dict]) -> int:
        """批量写入事件检测结果"""
        if not events:
            return 0

        conn = self.connect()
        sql = """
            INSERT INTO market_events
                (stock_code, event_type, event_subtype, event_desc, signal, news_date)
            VALUES
                (%s, %s, %s, %s, %s, %s)
        """
        rows = []
        for e in events:
            rows.append((
                e.get("stock_code", "000000"),
                e.get("event_type", "政策"),
                e.get("event_subtype", ""),
                e.get("event_desc", ""),
                e.get("signal", "关注"),
                e.get("news_date", date.today()),
            ))

        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
        print(f"[DB] 写入 {len(rows)} 条事件记录")
        return len(rows)

    def save_fear_index(self, data: dict) -> int:
        """写入恐慌指数"""
        conn = self.connect()
        sql = """
            INSERT INTO fear_index_history
                (vix, ovx, gvz, us10y, composite_score, risk_level, suggestion)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s)
        """
        with conn.cursor() as cur:
            cur.execute(sql, (
                data.get("vix"),
                data.get("ovx"),
                data.get("gvz"),
                data.get("us10y"),
                data.get("composite_score", 50),
                data.get("risk_level", "中"),
                data.get("suggestion", ""),
            ))
        conn.commit()
        print(f"[DB] 写入恐慌指数 (score={data.get('composite_score')})")
        return cur.rowcount

    # ─── 查询接口 ─────────────────────────────

    def get_recent_sentiment(self, stock_code: str, days: int = 7) -> List[dict]:
        """获取最近 N 天的情绪指数"""
        conn = self.connect()
        sql = """
            SELECT stock_code, fear_greed_index, overall_sentiment,
                   positive_count, negative_count, neutral_count,
                   top_themes, risk_alerts, opportunity_hints, analyzed_at
            FROM sentiment_aggregate
            WHERE stock_code = %s
              AND analyzed_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            ORDER BY analyzed_at DESC
        """
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, (stock_code, days))
            return cur.fetchall()

    def get_recent_events(self, stock_code: str = None, days: int = 7) -> List[dict]:
        """获取最近的事件"""
        conn = self.connect()
        if stock_code:
            sql = """
                SELECT * FROM market_events
                WHERE stock_code = %s AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                ORDER BY created_at DESC
            """
            params = (stock_code, days)
        else:
            sql = """
                SELECT * FROM market_events
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                ORDER BY created_at DESC
            """
            params = (days,)
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
