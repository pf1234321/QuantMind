"""个股诊断的基本面风险识别。

现有财务表没有商誉、质押比例、审计意见等专用字段，因此本模块只使用：
- trade_stock_financial 的利润、负债、现金流、资产、权益
- trade_stock_announcement 的标题关键词
- 股票名称中的 ST / *ST 标记

无法直接验证的标签会标记为 proxy，并在 evidence 中说明数据来源。
"""
from __future__ import annotations

import math
import re
from typing import Any

RULE_VERSION = "fundamental-risk-v1"
LOOKBACK_ANNOUNCEMENTS = 180
LOOKBACK_LIMIT = 80

PROFIT_DECLINE_PERIODS = 3
HIGH_DEBT_RATIO = 70.0
LOW_CURRENT_RATIO = 1.0
NEGATIVE_CASHFLOW_PERIODS = 2
HIGH_GROWTH_REVENUE = 20.0
LOW_MARGIN = 5.0
MARGIN_DROP = 3.0
INVENTORY_PROXY_RATIO = 0.45
RECEIVABLE_PROXY_RATIO = 0.35

EVENT_RULES: tuple[tuple[str, str, str, int, tuple[str, ...]], ...] = (
    ("unlock", "event", "解禁", 18, ("解禁", "限售股上市", "限售股份上市")),
    ("large_reduction", "event", "大额减持", 22, ("减持", "减持计划", "股份减持")),
    ("st_warning", "event", "ST", 28, ("ST", "*ST", "风险警示", "其他风险警示")),
    ("delist_warning", "event", "退市风险提示", 35, ("退市", "终止上市", "退市风险警示")),
    ("audit_non_standard", "financial_report", "审计非标意见", 30, ("非标意见", "保留意见", "无法表示意见", "否定意见", "带强调事项段")),
    ("auditor_change", "financial_report", "频繁更换会计师", 18, ("更换会计师", "变更会计师", "会计师事务所变更", "改聘会计师")),
    ("goodwill", "profit", "大额商誉", 20, ("商誉减值", "商誉")),
    ("high_pledge", "profit", "高质押", 20, ("股权质押", "股票质押", "质押")),
    ("high_interest_debt", "profit", "高有息负债", 16, ("有息负债", "债券违约", "债务违约", "逾期债务")),
    ("inventory_abnormal", "financial_report", "大额存货异常", 16, ("存货跌价", "存货异常", "库存积压")),
    ("receivable_abnormal", "financial_report", "应收账款异常", 16, ("应收账款", "坏账准备", "坏账计提")),
)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metric_value(metrics: dict[str, Any], field: str) -> float | None:
    item = metrics.get(field)
    if isinstance(item, dict):
        return _number(item.get("value"))
    return _number(item)


def _history_values(history: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in history:
        number = _number(row.get(field))
        if number is not None:
            values.append(number)
    return values


def _consecutive_decline(values: list[float], periods: int) -> bool:
    if len(values) < periods:
        return False
    window = values[:periods]
    return all(window[index] < window[index + 1] for index in range(periods - 1))


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1) * 100


def _announcement_text(row: dict[str, Any]) -> str:
    return " ".join(str(row.get(field) or "") for field in ("title", "ann_title", "keyword_hit", "category"))


def _match_keywords(text: str, keywords: tuple[str, ...]) -> str | None:
    for keyword in keywords:
        if keyword and keyword in text:
            return keyword
    return None


def _tag(
    tag_id: str,
    category: str,
    name: str,
    level: str,
    score: int,
    description: str,
    evidence: dict[str, Any],
    proxy: bool = False,
) -> dict[str, Any]:
    return {
        "id": tag_id,
        "category": category,
        "name": name,
        "level": level,
        "score": score,
        "description": description,
        "proxy": proxy,
        "evidence": evidence,
    }


def _level_from_score(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _profit_tags(fundamental: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = fundamental.get("metrics") or {}
    history = fundamental.get("history") or []
    tags: list[dict[str, Any]] = []

    profits = _history_values(history, "net_profit")
    if _consecutive_decline(profits, PROFIT_DECLINE_PERIODS):
        tags.append(_tag(
            "profit_decline",
            "profit",
            "连续扣非净利润下滑",
            "high",
            28,
            f"最近 {PROFIT_DECLINE_PERIODS} 期净利润连续下滑，当前用净利润代理扣非净利润。",
            {"net_profit": profits[:PROFIT_DECLINE_PERIODS], "proxy_field": "net_profit"},
            proxy=True,
        ))

    revenues = _history_values(history, "revenue")
    margins = _history_values(history, "net_margin")
    revenue_growth = _growth(revenues[0], revenues[1]) if len(revenues) >= 2 else None
    latest_margin = margins[0] if margins else _metric_value(metrics, "net_margin")
    previous_margin = margins[1] if len(margins) >= 2 else None
    if (
        revenue_growth is not None
        and revenue_growth >= HIGH_GROWTH_REVENUE
        and latest_margin is not None
        and (
            latest_margin < LOW_MARGIN
            or (previous_margin is not None and previous_margin - latest_margin >= MARGIN_DROP)
        )
    ):
        tags.append(_tag(
            "pe_trap",
            "profit",
            "PE 陷阱",
            "high",
            24,
            "收入仍在扩张，但净利率偏低或明显回落，存在高景气低质量利润下行预警。",
            {
                "revenue_growth": round(revenue_growth, 2),
                "net_margin": latest_margin,
                "previous_net_margin": previous_margin,
            },
            proxy=True,
        ))

    debt_ratio = _metric_value(metrics, "debt_ratio")
    current_ratio = _metric_value(metrics, "current_ratio")
    if debt_ratio is not None and debt_ratio >= HIGH_DEBT_RATIO:
        tags.append(_tag(
            "high_interest_debt",
            "profit",
            "高有息负债",
            "high" if debt_ratio >= 85 else "medium",
            22 if debt_ratio >= 85 else 16,
            f"资产负债率 {debt_ratio:.2f}%，用总负债率代理有息负债压力。",
            {"debt_ratio": debt_ratio},
            proxy=True,
        ))
    elif current_ratio is not None and current_ratio < LOW_CURRENT_RATIO:
        tags.append(_tag(
            "high_interest_debt",
            "profit",
            "高有息负债",
            "medium",
            14,
            f"流动比率 {current_ratio:.2f} 低于 1，短期偿债压力较大。",
            {"current_ratio": current_ratio},
            proxy=True,
        ))
    return tags


def _report_tags(fundamental: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = fundamental.get("metrics") or {}
    history = fundamental.get("history") or []
    tags: list[dict[str, Any]] = []

    cashflows = _history_values(history, "operating_cashflow")
    profits = _history_values(history, "net_profit")
    if (
        len(cashflows) >= NEGATIVE_CASHFLOW_PERIODS
        and all(value < 0 for value in cashflows[:NEGATIVE_CASHFLOW_PERIODS])
        and profits and profits[0] > 0
    ):
        tags.append(_tag(
            "cashflow_mismatch",
            "financial_report",
            "经营现金流异常",
            "medium",
            14,
            "净利润为正，但最近两期经营现金流为负，报表质量需要警惕。",
            {"operating_cashflow": cashflows[:NEGATIVE_CASHFLOW_PERIODS], "net_profit": profits[0]},
        ))

    assets = _metric_value(metrics, "total_assets")
    equity = _metric_value(metrics, "total_equity")
    revenue = _metric_value(metrics, "revenue")
    if assets and equity is not None and revenue:
        working_capital = assets - equity
        inventory_proxy = working_capital / assets if assets else None
        receivable_proxy = working_capital / revenue if revenue else None
        if inventory_proxy is not None and inventory_proxy >= INVENTORY_PROXY_RATIO:
            tags.append(_tag(
                "inventory_abnormal",
                "financial_report",
                "大额存货异常",
                "medium",
                12,
                "缺少存货字段，用（总资产-净资产）/总资产作为营运资产占比代理。",
                {"working_capital_to_assets": round(inventory_proxy, 4)},
                proxy=True,
            ))
        if receivable_proxy is not None and receivable_proxy >= RECEIVABLE_PROXY_RATIO:
            tags.append(_tag(
                "receivable_abnormal",
                "financial_report",
                "应收账款异常",
                "medium",
                12,
                "缺少应收账款字段，用（总资产-净资产）/营收作为营运资产周转代理。",
                {"working_capital_to_revenue": round(receivable_proxy, 4)},
                proxy=True,
            ))
    return tags


def _event_tags(stock_name: str | None, announcements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tags: list[dict[str, Any]] = []
    name = str(stock_name or "")
    if re.search(r"\*?ST", name, re.IGNORECASE):
        tags.append(_tag(
            "st_warning",
            "event",
            "ST",
            "high",
            28,
            f"股票名称包含风险警示标记：{name}。",
            {"stock_name": name},
        ))
    if "退市" in name:
        tags.append(_tag(
            "delist_warning",
            "event",
            "退市风险提示",
            "high",
            35,
            f"股票名称包含退市相关标记：{name}。",
            {"stock_name": name},
        ))

    matched: dict[str, dict[str, Any]] = {}
    for row in announcements:
        text = _announcement_text(row)
        if not text:
            continue
        for tag_id, category, name_label, score, keywords in EVENT_RULES:
            if tag_id in matched:
                continue
            keyword = _match_keywords(text, keywords)
            if not keyword:
                continue
            matched[tag_id] = _tag(
                tag_id,
                category,
                name_label,
                "high" if score >= 22 else "medium",
                score,
                f"公告标题命中“{keyword}”。",
                {
                    "keyword": keyword,
                    "title": row.get("title") or row.get("ann_title"),
                    "ann_date": str(row.get("ann_date") or "")[:10],
                    "source": row.get("source"),
                },
            )
    tags.extend(matched.values())
    return tags


def _dedupe(tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for tag in tags:
        current = unique.get(tag["id"])
        if current is None or int(tag["score"]) > int(current["score"]):
            unique[tag["id"]] = tag
    return sorted(unique.values(), key=lambda item: (-int(item["score"]), item["id"]))


def calculate_fundamental_risk(
    fundamental: dict[str, Any] | None,
    stock_name: str | None = None,
    announcements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """输出基本面风险得分 0-100，以及风险标签列表。"""
    if not fundamental:
        return {
            "score": 55,
            "level": "medium",
            "status": "blocked",
            "rule_version": RULE_VERSION,
            "tags": [_tag("data_missing", "data", "基本面数据不可用", "medium", 55, "基本面结果为空，无法识别盈利、财报和事件风险。", {})],
            "categories": {"profit": 0, "financial_report": 0, "event": 0, "data": 55},
        }

    tags = _dedupe(_profit_tags(fundamental) + _report_tags(fundamental) + _event_tags(stock_name, announcements or []))
    score = min(100, sum(int(tag["score"]) for tag in tags))
    categories = {"profit": 0, "financial_report": 0, "event": 0}
    for tag in tags:
        category = tag["category"]
        if category in categories:
            categories[category] += int(tag["score"])
    return {
        "score": score,
        "level": _level_from_score(score),
        "status": "completed",
        "rule_version": RULE_VERSION,
        "tags": tags,
        "categories": {key: min(100, value) for key, value in categories.items()},
    }


def to_risk_items(fundamental_risk: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for tag in fundamental_risk.get("tags") or []:
        items.append({
            "type": tag["id"],
            "level": tag["level"],
            "source": "fundamental",
            "category": tag.get("category"),
            "description": tag.get("description"),
            "score": tag.get("score"),
            "proxy": tag.get("proxy", False),
            "evidence": tag.get("evidence") or {},
        })
    return items
