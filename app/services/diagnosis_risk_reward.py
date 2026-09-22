"""个股诊断的可复现风险收益和行业比较计算。"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd

RULE_VERSION = "risk-reward-v2"
STOP_MODES = ("atr", "trailing_atr", "support")
DEFAULT_ATR_PERIOD = 14
DEFAULT_TRAILING_LOOKBACK = 20


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any, digits: int = 4) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None


def _int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, number))


def _fingerprint(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _series_frame(series: list[dict[str, Any]] | None) -> pd.DataFrame:
    frame = pd.DataFrame(series or [])
    if frame.empty:
        return frame
    for source, target in (("high_price", "high"), ("low_price", "low"), ("close_price", "close")):
        if target not in frame.columns and source in frame.columns:
            frame[target] = frame[source]
    return frame


def _annualized_hv(returns: pd.Series, window: int) -> float | None:
    sample = returns.tail(window).dropna()
    if len(sample) < 2:
        return None
    return _number(sample.std(ddof=1) * np.sqrt(252)) if len(sample) > 1 else None


def _atr(frame: pd.DataFrame, period: int = DEFAULT_ATR_PERIOD) -> float | None:
    if frame.empty or not {"high", "low", "close"}.issubset(frame.columns):
        return None
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    if high.dropna().empty or low.dropna().empty or close.dropna().empty:
        return None
    previous = close.shift(1)
    true_range = pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    atr = true_range.rolling(period, min_periods=period).mean()
    if atr.dropna().empty:
        return None
    return _number(atr.iloc[-1])


def _atr_multiple_from_hv(hv: float | None, override: float | None) -> float:
    if override is not None and override > 0:
        return round(min(10.0, max(0.5, override)), 2)
    if hv is None or hv <= 0:
        return 2.0
    return round(min(3.0, max(1.5, 1.5 + (hv - 0.15) / 0.20)), 2)


def _valid_stop(price: float | None, close: float) -> float | None:
    if price is None or price <= 0 or price >= close:
        return None
    return price


def _stop_trigger(stop_type: str, price: float, *, multiple: float, lookback: int, risk_budget: float) -> str:
    formatted = f"{_round(price, 4)}"
    if stop_type == "atr":
        return f"收盘价跌破 {formatted}（入场价 - {multiple}×ATR14）"
    if stop_type == "trailing_atr":
        return f"收盘价跌破 {formatted}（近{lookback}日高点 - {multiple}×ATR14）"
    if stop_type == "support":
        return f"收盘价跌破 {formatted}（20日低点/技术支撑）"
    if stop_type == "budget":
        return f"收盘价跌破 {formatted}（风险预算 {abs(risk_budget):.0%}）"
    return f"收盘价跌破 {formatted}"


def calculate_volatility(market: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """计算 HV20、HV60 年化波动率和 ATR14。"""
    config = config or {}
    frame = _series_frame(market.get("series") or [])
    closes = pd.to_numeric(frame["close"], errors="coerce").dropna() if "close" in frame.columns else pd.Series(dtype=float)
    returns = closes.pct_change().dropna()
    atr_period = _int(config.get("atr_period"), DEFAULT_ATR_PERIOD, 2, 60)
    hv20 = _annualized_hv(returns, 20)
    hv60 = _annualized_hv(returns, 60)
    atr14 = _atr(frame, atr_period)
    return {
        "hv20": _round(hv20),
        "hv60": _round(hv60),
        "atr14": _round(atr14),
        "atr_period": atr_period,
        "sample_count": int(len(closes)),
        "return_count": int(len(returns)),
        "method": "hv=std(daily_returns)*sqrt(252); atr=mean(true_range, 14)",
    }


def calculate_stop_loss(
    close: float,
    support: float | None,
    volatility: dict[str, Any],
    config: dict[str, Any] | None = None,
    series: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """按配置计算 ATR 动态止损、移动 ATR 止损，并用 20 日低点兜底。"""
    config = config or {}
    risk_budget = abs(_number(config.get("risk_budget")) or 0.08)
    stop_mode = str(config.get("stop_mode") or "atr").strip().lower()
    if stop_mode not in STOP_MODES:
        stop_mode = "atr"
    lookback = _int(config.get("trailing_lookback"), DEFAULT_TRAILING_LOOKBACK, 5, 120)
    hv = _number(volatility.get("hv20")) or _number(volatility.get("hv60"))
    multiple = _atr_multiple_from_hv(hv, _number(config.get("atr_multiple")))
    atr14 = _number(volatility.get("atr14"))
    frame = _series_frame(series)
    recent_high = None
    if not frame.empty and "high" in frame.columns:
        highs = pd.to_numeric(frame["high"], errors="coerce").dropna()
        if not highs.empty:
            recent_high = _number(highs.tail(lookback).max())
    atr_stop = _valid_stop(close - multiple * atr14, close) if atr14 is not None and atr14 > 0 else None
    trailing_stop = _valid_stop(recent_high - multiple * atr14, close) if recent_high is not None and atr14 is not None and atr14 > 0 else None
    support_stop = _valid_stop(support, close)
    budget_stop = _valid_stop(close * (1 - risk_budget), close)
    candidates = {
        "atr": _round(atr_stop),
        "trailing_atr": _round(trailing_stop),
        "support": _round(support_stop),
        "budget": _round(budget_stop),
    }
    selected = {"atr": atr_stop, "trailing_atr": trailing_stop, "support": support_stop}.get(stop_mode)
    stop_type = stop_mode
    fallback_used = False
    if selected is None:
        for fallback_type, fallback_price in (("support", support_stop), ("budget", budget_stop), ("atr", atr_stop), ("trailing_atr", trailing_stop)):
            if fallback_price is not None:
                selected = fallback_price
                stop_type = fallback_type
                fallback_used = True
                break
    return {
        "type": stop_type if selected is not None else None,
        "price": _round(selected),
        "trigger": _stop_trigger(stop_type, selected, multiple=multiple, lookback=lookback, risk_budget=risk_budget) if selected is not None else None,
        "atr_multiple": multiple,
        "fallback_used": fallback_used,
        "requested_mode": stop_mode,
        "candidates": candidates,
        "recent_high": _round(recent_high),
        "method": "atr_dynamic_with_trailing_and_support_fallback",
    }


def calculate_risk_reward(market: dict[str, Any], technical: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """只使用已存在的行情和技术快照计算，绝不生成模型价格。"""
    config = config or {}
    close = _number(market.get("close"))
    support = _number(technical.get("support"))
    resistance = _number(technical.get("resistance"))
    volatility = calculate_volatility(market, config)
    if close is None or close <= 0:
        return {"status": "blocked", "reason": "当前价格缺失或无效", "volatility": volatility, "rule_version": RULE_VERSION}
    stop = calculate_stop_loss(close, support, volatility, config, market.get("series") or [])
    if resistance is None or resistance <= close:
        return {
            "status": "blocked",
            "reason": "技术支撑位或阻力位不足，无法计算价格区间",
            "volatility": volatility,
            "stop_loss": stop,
            "rule_version": RULE_VERSION,
        }
    if stop.get("price") is None:
        return {
            "status": "blocked",
            "reason": "止损价无法根据 ATR、20日低点或风险预算计算",
            "volatility": volatility,
            "stop_loss": stop,
            "rule_version": RULE_VERSION,
        }
    risk_budget = abs(_number(config.get("risk_budget")) or 0.08)
    min_days = _int(config.get("min_holding_days"), 5, 1, 365)
    max_days = _int(config.get("max_holding_days"), 60, 1, 365)
    if max_days < min_days:
        min_days, max_days = max_days, min_days
    stop_loss = stop["price"]
    target_low = max(close, min(resistance, close * (1 + max(0.01, risk_budget))))
    target_high = max(target_low, resistance)
    downside = close - stop_loss
    upside = target_low - close
    ratio = (upside / downside) if downside > 0 else None
    holding_volatility = _number(volatility.get("hv20")) or _number(volatility.get("hv60"))
    volatility_factor = holding_volatility if holding_volatility is not None and holding_volatility > 0 else 0.5
    holding_days = min(max_days, max(min_days, round(20 / max(volatility_factor, 0.05))))
    inputs = {
        "close": close,
        "support": support,
        "resistance": resistance,
        "hv20": volatility.get("hv20"),
        "hv60": volatility.get("hv60"),
        "atr14": volatility.get("atr14"),
        "atr_multiple": stop.get("atr_multiple"),
        "stop_mode": stop.get("requested_mode"),
        "risk_budget": risk_budget,
    }
    return {
        "status": "completed",
        "target_price": {"low": _round(target_low), "high": _round(target_high), "method": "technical_resistance_and_risk_budget"},
        "expected_return": {"low": _round((target_low / close - 1) * 100, 2), "high": _round((target_high / close - 1) * 100, 2), "unit": "%"},
        "holding_period": {"days": holding_days, "min_days": min_days, "max_days": max_days, "method": "hv20_adjusted_window"},
        "stop_loss": stop,
        "volatility": volatility,
        "risk_reward_ratio": _round(ratio, 2),
        "inputs": inputs,
        "formula": "stop=entry-n*ATR14(n from HV); fallback=20d_low; risk_reward=(target_low-close)/(close-stop_loss)",
        "data_as_of": market.get("data_as_of"),
        "data_source": market.get("data_source"),
        "rule_version": RULE_VERSION,
        "confidence": _round(min(1, volatility.get("return_count", 0) / 60), 2),
        "quality_checks": {
            "history_window": volatility.get("sample_count"),
            "hv20_available": volatility.get("hv20") is not None,
            "hv60_available": volatility.get("hv60") is not None,
            "atr14_available": volatility.get("atr14") is not None,
            "volatility_available": holding_volatility is not None,
            "stop_fallback_used": bool(stop.get("fallback_used")),
        },
        "input_fingerprint": _fingerprint(inputs),
    }


def build_industry_comparison(symbol: str, stock: dict[str, Any] | None, peers: list[dict[str, Any]]) -> dict[str, Any]:
    """用行业分类快照和可用行情指标生成透明的同行比较。"""
    stock = stock or {}
    sector = stock.get("sector_2") or stock.get("sector_1") or stock.get("sector_3")
    rows = [row for row in peers if row.get("stock_code") != symbol]
    if not sector:
        return {"status": "blocked", "reason": "股票行业信息缺失", "sector": None, "peers": []}
    if len(rows) < 2:
        return {"status": "partial", "reason": "同行样本不足", "sector": sector, "peers": rows, "sample_count": len(rows)}
    return {"status": "completed", "sector": sector, "sample_count": len(rows), "peer_codes": [row.get("stock_code") for row in rows],
            "metrics": {"sample_count": len(rows), "available_fields": sorted({key for row in rows for key, value in row.items() if value is not None})},
            "peers": rows, "data_quality": {"missing_industry": False, "sample_shortage": False}, "rule_version": RULE_VERSION}
