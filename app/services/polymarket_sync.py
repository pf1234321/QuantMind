# -*- coding: utf-8 -*-
"""Polymarket 预测市场信号同步（搬运自 skills/sentiment-analysis/scripts/polymarket_monitor.py）

- 通过 Gamma API 抓取关键词相关的预测市场
- 解析概率 / 交易量 / 流动性
- 检测聪明钱信号
- 生成资产配置建议
- 全部写入 `polymarket_signal` 表

国内网络可能无法直接访问 Polymarket，httpx 失败时静默返回空，不影响其他任务。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.database import execute_many, execute_query, execute_update

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"

DEFAULT_KEYWORDS = [
    "Iran", "China", "tariff", "war", "ceasefire",
    "sanctions", "Fed", "interest rate", "recession",
    "oil", "Bitcoin", "S&P 500",
]

EVENT_ASSET_MAP = {
    "war": {
        "high_prob": {"action": "做多黄金/原油，做空科技股", "reason": "避险资产上涨"},
        "low_prob": {"action": "平仓避险头寸，买入风险资产", "reason": "风险情绪修复"},
    },
    "ceasefire": {
        "high_prob": {"action": "平仓原油多头，买入被制裁国资产", "reason": "和平利好风险资产"},
        "low_prob": {"action": "维持避险配置", "reason": "冲突持续"},
    },
    "tariff": {
        "high_prob": {"action": "回避出口型企业，关注内需板块", "reason": "关税冲击出口"},
        "low_prob": {"action": "关注出口复苏机会", "reason": "贸易环境改善"},
    },
    "recession": {
        "high_prob": {"action": "增配国债和黄金，减仓周期股", "reason": "经济衰退避险"},
        "low_prob": {"action": "增配成长股和周期股", "reason": "经济前景向好"},
    },
    "interest rate": {
        "high_prob": {"action": "利率上行预期，关注银行股", "reason": "加息利好银行净息差"},
        "low_prob": {"action": "降息预期，关注成长股", "reason": "低利率利好高估值标的"},
    },
}


def init_schema() -> None:
    execute_update(
        """CREATE TABLE IF NOT EXISTS polymarket_signal (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            event_id VARCHAR(128) NOT NULL,
            market_id VARCHAR(128) NOT NULL,
            event_title VARCHAR(512) NULL,
            question TEXT NULL,
            keyword VARCHAR(64) NOT NULL,
            yes_probability DECIMAL(6,2) NULL,
            no_probability DECIMAL(6,2) NULL,
            volume_usd DECIMAL(20,2) NULL,
            liquidity_usd DECIMAL(20,2) NULL,
            signal_strength VARCHAR(32) NULL,
            asset_suggestion VARCHAR(255) NULL,
            end_date DATE NULL,
            description TEXT NULL,
            fetched_at DATETIME NOT NULL,
            UNIQUE KEY uq_polymarket_market_fetched (market_id, fetched_at),
            KEY idx_polymarket_keyword (keyword, fetched_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )


def fetch_events(keyword: str, limit: int = 20) -> list[dict]:
    """从 Polymarket Gamma API 获取相关预测市场事件。

    国内不可达时返回空 list（不抛错）。
    """
    try:
        import httpx
    except ImportError:
        logger.warning("[Polymarket] httpx 未安装，跳过关键词=%s", keyword)
        return []

    params = {"active": "true", "closed": "false", "search": keyword, "limit": limit}
    headers = {
        "User-Agent": "Mozilla/5.0 QuantMind",
        "Accept": "application/json",
    }
    try:
        resp = httpx.get(
            f"{GAMMA_API_BASE}/events",
            params=params,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 国内外不通常见，吞掉不影响后续
        logger.info("[Polymarket] 关键词=%s 抓取失败: %s", keyword, exc)
        return []

    if not data:
        logger.info("[Polymarket] 关键词=%s 未找到活跃市场", keyword)
        return []
    return data


def _format_volume(volume: float) -> str:
    if volume >= 1_000_000_000:
        return f"${volume / 1_000_000_000:.1f}B"
    if volume >= 1_000_000:
        return f"${volume / 1_000_000:.1f}M"
    if volume >= 1_000:
        return f"${volume / 1_000:.1f}K"
    return f"${volume:.0f}"


def parse_markets(events: list[dict], min_volume: float = 0) -> list[dict]:
    markets: list[dict] = []
    for event in events:
        event_title = event.get("title", "")
        event_id = event.get("id", "")
        for market in event.get("markets", []):
            outcome_prices = market.get("outcomePrices", "[]")
            if isinstance(outcome_prices, str):
                try:
                    prices = json.loads(outcome_prices)
                except (json.JSONDecodeError, TypeError):
                    prices = [0, 0]
            else:
                prices = outcome_prices or [0, 0]
            yes_price = float(prices[0]) if len(prices) > 0 else 0
            no_price = float(prices[1]) if len(prices) > 1 else 0
            volume = float(market.get("volume", 0) or 0)
            if volume < min_volume:
                continue
            liquidity = float(market.get("liquidity", 0) or 0)
            yes_pct = round(yes_price * 100, 1)
            no_pct = round(no_price * 100, 1)
            if yes_pct >= 80:
                signal = "极强确定性"
            elif yes_pct >= 60:
                signal = "较强倾向"
            elif yes_pct >= 40:
                signal = "不确定（波动率机会）"
            elif yes_pct >= 20:
                signal = "较强否定"
            else:
                signal = "极强否定"
            markets.append({
                "event_id": event_id,
                "event_title": event_title,
                "market_id": market.get("id", ""),
                "question": market.get("question", ""),
                "yes_probability": yes_pct,
                "no_probability": no_pct,
                "volume_usd": round(volume, 2),
                "volume_display": _format_volume(volume),
                "liquidity_usd": round(liquidity, 2),
                "signal_strength": signal,
                "end_date": market.get("endDate", "")[:10] if market.get("endDate") else None,
                "description": (market.get("description") or "")[:200],
            })
    markets.sort(key=lambda x: x["volume_usd"], reverse=True)
    return markets


def detect_smart_money_signals(markets: list[dict]) -> list[dict]:
    if not markets:
        return []
    volumes = [m["volume_usd"] for m in markets if m["volume_usd"] > 0]
    if not volumes:
        return []
    avg_volume = sum(volumes) / len(volumes)
    signals: list[dict] = []
    for m in markets:
        reasons: list[str] = []
        if m["volume_usd"] > avg_volume * 3:
            reasons.append(f"交易量 {m['volume_display']} 远超平均值 {_format_volume(avg_volume)}")
        if m["yes_probability"] >= 85 or m["yes_probability"] <= 15:
            direction = "Yes" if m["yes_probability"] >= 85 else "No"
            prob = m["yes_probability"] if direction == "Yes" else m["no_probability"]
            reasons.append(f"概率高度倾向 {direction}({prob}%)，市场有强烈共识")
        if m["liquidity_usd"] > 1_000_000 and (m["yes_probability"] >= 70 or m["yes_probability"] <= 30):
            reasons.append(f"高流动性 {_format_volume(m['liquidity_usd'])} 支撑价格稳定性")
        if reasons:
            signals.append({
                "question": m["question"],
                "yes_probability": m["yes_probability"],
                "volume": m["volume_display"],
                "signal_reasons": reasons,
                "alert_level": "高" if len(reasons) >= 2 else "中",
            })
    return signals


def generate_asset_suggestions(markets: list[dict]) -> list[dict]:
    suggestions: list[dict] = []
    question_pairs = [(m, (m.get("question") or "").lower()) for m in markets]
    for event_type, actions in EVENT_ASSET_MAP.items():
        for m, q_lower in question_pairs:
            if event_type in q_lower:
                prob = m["yes_probability"]
                if prob >= 60:
                    suggestion = actions["high_prob"].copy()
                    suggestion["trigger"] = f"{m['question']} (概率: {prob}%)"
                    suggestion["volume"] = m["volume_display"]
                    suggestions.append(suggestion)
                elif prob <= 30:
                    suggestion = actions["low_prob"].copy()
                    suggestion["trigger"] = f"{m['question']} (概率: {prob}%)"
                    suggestion["volume"] = m["volume_display"]
                    suggestions.append(suggestion)
                break
    return suggestions


def sync_polymarket(
    keywords: list[str] | None = None,
    min_volume: float = 10000,
    top_n: int = 20,
) -> dict:
    """手动 / 定时入口：抓取 + 入库 + 统计。"""
    search_keywords = keywords or DEFAULT_KEYWORDS
    if isinstance(search_keywords, str):
        search_keywords = [k.strip() for k in search_keywords.split(",") if k.strip()]
    search_keywords = search_keywords[:12]  # 安全上限

    all_markets: list[dict] = []
    fetched_at = datetime.now().replace(microsecond=0)

    for keyword in search_keywords:
        events = fetch_events(keyword, limit=top_n)
        if not events:
            continue
        markets = parse_markets(events, min_volume=min_volume)
        for m in markets:
            m["keyword"] = keyword
        all_markets.extend(markets)

    # 去重（同一 market 可能被多个关键词命中）
    seen: set[str] = set()
    unique: list[dict] = []
    for m in all_markets:
        if m["market_id"] in seen:
            continue
        seen.add(m["market_id"])
        unique.append(m)
    all_markets = unique

    # 写库
    if all_markets:
        rows = []
        for m in all_markets:
            rows.append((
                m["event_id"], m["market_id"], m["event_title"], m["question"],
                m["keyword"], m["yes_probability"], m["no_probability"],
                m["volume_usd"], m["liquidity_usd"], m["signal_strength"],
                "",  # asset_suggestion（每个市场不直接给，单独列表）
                m["end_date"], m["description"], fetched_at,
            ))
        execute_many(
            """INSERT INTO polymarket_signal
                (event_id, market_id, event_title, question, keyword,
                 yes_probability, no_probability, volume_usd, liquidity_usd,
                 signal_strength, asset_suggestion, end_date, description, fetched_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            rows,
        )

    smart_signals = detect_smart_money_signals(all_markets)
    asset_suggestions = generate_asset_suggestions(all_markets)
    return {
        "status": "success",
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
        "keywords": search_keywords,
        "total_markets": len(all_markets),
        "smart_money_signals": len(smart_signals),
        "asset_suggestions": len(asset_suggestions),
        "signals_sample": smart_signals[:10],
        "asset_suggestions_sample": asset_suggestions[:10],
    }


def list_signals(
    keyword: str | None = None,
    limit: int = 50,
    min_volume_usd: float | None = None,
) -> list[dict]:
    sql = (
        "SELECT event_id, market_id, event_title, question, keyword, "
        "yes_probability, no_probability, volume_usd, liquidity_usd, "
        "signal_strength, end_date, description, fetched_at "
        "FROM polymarket_signal"
    )
    params: list[Any] = []
    conds: list[str] = []
    if keyword:
        conds.append("keyword=%s")
        params.append(keyword)
    if min_volume_usd is not None:
        conds.append("volume_usd >= %s")
        params.append(min_volume_usd)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY volume_usd DESC LIMIT %s"
    params.append(int(limit))
    rows = execute_query(sql, params)
    return [
        {
            **r,
            "yes_probability": float(r["yes_probability"]) if r.get("yes_probability") is not None else None,
            "no_probability": float(r["no_probability"]) if r.get("no_probability") is not None else None,
            "volume_usd": float(r["volume_usd"]) if r.get("volume_usd") is not None else None,
            "liquidity_usd": float(r["liquidity_usd"]) if r.get("liquidity_usd") is not None else None,
        }
        for r in rows
    ]


def get_smart_money_signals(limit: int = 20) -> list[dict]:
    """基于最新 fetch 时间，按"高交易量 + 极端概率"二次筛选。"""
    last = execute_query("SELECT MAX(fetched_at) AS mx FROM polymarket_signal")
    if not last or not last[0].get("mx"):
        return []
    mx = last[0]["mx"]
    rows = execute_query(
        """SELECT market_id, question, keyword, yes_probability, volume_usd,
                  liquidity_usd, signal_strength
           FROM polymarket_signal
           WHERE fetched_at=%s
             AND (yes_probability>=85 OR yes_probability<=15)
             AND volume_usd>50000""",
        (mx,),
    )
    out: list[dict] = []
    for r in rows[: int(limit)]:
        yes_pct = float(r["yes_probability"])
        direction = "Yes" if yes_pct >= 50 else "No"
        prob = yes_pct if direction == "Yes" else 100 - yes_pct
        out.append({
            "question": r["question"],
            "keyword": r["keyword"],
            "yes_probability": yes_pct,
            "volume_display": _format_volume(float(r["volume_usd"])),
            "signal_reasons": [
                f"概率高度倾向 {direction}({prob:.1f}%)",
                f"交易量 {_format_volume(float(r['volume_usd']))}",
            ],
            "alert_level": "高",
        })
    return out


def get_asset_suggestions(limit: int = 20) -> list[dict]:
    """基于最新 fetch 重新运行 generate_asset_suggestions。"""
    last = execute_query("SELECT MAX(fetched_at) AS mx FROM polymarket_signal")
    if not last or not last[0].get("mx"):
        return []
    mx = last[0]["mx"]
    rows = execute_query(
        """SELECT market_id, question, keyword, yes_probability, volume_usd
           FROM polymarket_signal WHERE fetched_at=%s ORDER BY volume_usd DESC""",
        (mx,),
    )
    if not rows:
        return []
    markets = [
        {
            "question": r["question"],
            "yes_probability": float(r["yes_probability"]),
            "volume_display": _format_volume(float(r["volume_usd"])),
        }
        for r in rows
    ]
    return generate_asset_suggestions(markets)[: int(limit)]