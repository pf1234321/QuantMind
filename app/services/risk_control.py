"""Deterministic portfolio and trade-plan risk control."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from typing import Any

from app.database import execute_query, get_connection

DECISION_ORDER = {"APPROVE": 0, "WARN": 1, "REJECT": 2, "HALT": 3}
DEFAULT_RULES = {
    "max_single_weight": 0.20,
    "max_industry_weight": 0.40,
    "max_total_weight": 0.95,
    "warning_daily_loss": 0.03,
    "halt_daily_loss": 0.05,
    "warning_drawdown": 0.10,
    "halt_drawdown": 0.20,
    "warning_atr_distance": 0.05,
    "macro_warning_score": 35,
    "macro_halt_score": 20,
}


def init_risk_schema() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS risk_portfolio_snapshot (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    portfolio_id VARCHAR(64) NOT NULL,
                    total_assets DECIMAL(20,4) NULL, cash DECIMAL(20,4) NULL,
                    holdings_value DECIMAL(20,4) NULL, total_weight DECIMAL(12,8) NULL,
                    daily_pnl DECIMAL(20,4) NULL, daily_pnl_ratio DECIMAL(12,8) NULL,
                    drawdown DECIMAL(12,8) NULL, payload_json LONGTEXT NOT NULL,
                    snapshot_at DATETIME(6) NOT NULL, INDEX idx_risk_portfolio_time (portfolio_id, snapshot_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS risk_decision (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    decision_key CHAR(64) NOT NULL, portfolio_id VARCHAR(64) NOT NULL,
                    stock_code VARCHAR(32) NULL, action VARCHAR(10) NULL,
                    decision VARCHAR(12) NOT NULL, risk_level VARCHAR(20) NOT NULL,
                    suggested_max_weight DECIMAL(12,8) NULL, rule_results_json LONGTEXT NOT NULL,
                    snapshot_json LONGTEXT NOT NULL, rule_version VARCHAR(32) NOT NULL,
                    created_at DATETIME(6) NOT NULL, UNIQUE KEY uq_risk_decision_key (decision_key),
                    KEY idx_risk_decision_time (created_at), KEY idx_risk_decision_stock (stock_code)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS risk_alert (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    alert_key CHAR(64) NOT NULL, portfolio_id VARCHAR(64) NOT NULL,
                    stock_code VARCHAR(32) NULL, alert_type VARCHAR(50) NOT NULL,
                    severity VARCHAR(12) NOT NULL, message VARCHAR(500) NOT NULL,
                    value_json LONGTEXT NULL, status VARCHAR(20) NOT NULL DEFAULT 'active',
                    acknowledged_at DATETIME(6) NULL, created_at DATETIME(6) NOT NULL,
                    UNIQUE KEY uq_risk_alert_key (alert_key), KEY idx_risk_alert_status (status, created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        conn.commit()
    finally:
        conn.close()


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _rule(rule_id: str, decision: str, reason: str, value: Any = None, threshold: Any = None, source: str = "request") -> dict[str, Any]:
    return {"rule": rule_id, "decision": decision, "reason": reason, "value": value, "threshold": threshold, "source": source, "data_as_of": str(date.today())}


def _latest_market(stock_code: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    rows = execute_query("SELECT trade_date, high_price, low_price, close_price, amount FROM trade_stock_daily WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 30", (stock_code,))
    return (rows[0] if rows else None, rows)


def _atr(rows: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(rows) < period + 1:
        return None
    ordered = list(reversed(rows))
    true_ranges = []
    for previous, current in zip(ordered, ordered[1:]):
        high, low, prev_close = _number(current.get("high_price")), _number(current.get("low_price")), _number(previous.get("close_price"))
        if high is None or low is None or prev_close is None:
            continue
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(true_ranges[-period:]) / period if len(true_ranges) >= period else None


def _source_rows(stock_code: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        result["fear_index"] = execute_query("SELECT composite_score, risk_level, suggestion, recorded_at FROM fear_index_history ORDER BY recorded_at DESC LIMIT 1")
    except Exception:
        result["fear_index"] = []
    try:
        result["events"] = execute_query("SELECT event_type, event_desc, signal, news_date, created_at FROM market_events WHERE stock_code=%s ORDER BY created_at DESC LIMIT 10", (stock_code,))
    except Exception:
        result["events"] = []
    try:
        result["signals"] = execute_query("SELECT signal_type, signal_date, signal_price, signal_status FROM chan_signals WHERE stock_code=%s ORDER BY signal_date DESC LIMIT 10", (stock_code,))
    except Exception:
        result["signals"] = []
    return result


def evaluate(payload: dict[str, Any], persist: bool = True) -> dict[str, Any]:
    stock_code = str(payload.get("stock_code") or "").strip()
    action = str(payload.get("action") or "buy").lower()
    portfolio_id = str(payload.get("portfolio_id") or "default")
    target_weight = _number(payload.get("target_weight"))
    rules = {**DEFAULT_RULES, **(payload.get("rules") or {})}
    portfolio = payload.get("portfolio") or {}
    results: list[dict[str, Any]] = []
    if action not in {"buy", "sell"}:
        results.append(_rule("action", "REJECT", "交易方向无效"))
    if target_weight is not None and target_weight > float(rules["max_single_weight"]):
        results.append(_rule("single_weight", "REJECT", "目标仓位超过单股上限", target_weight, rules["max_single_weight"]))
    total_weight = _number(portfolio.get("total_weight"))
    if action == "buy" and target_weight is not None and total_weight is not None and total_weight + target_weight > float(rules["max_total_weight"]):
        results.append(_rule("total_weight", "REJECT", "组合总仓位超过上限", total_weight + target_weight, rules["max_total_weight"]))
    industry_weight = _number(payload.get("industry_weight"))
    if industry_weight is not None and target_weight is not None and industry_weight + target_weight > float(rules["max_industry_weight"]):
        results.append(_rule("industry_concentration", "WARN", "行业集中度达到上限", industry_weight + target_weight, rules["max_industry_weight"]))
    daily_loss = abs(_number(portfolio.get("daily_pnl_ratio")) or 0) if (_number(portfolio.get("daily_pnl_ratio")) or 0) < 0 else 0
    drawdown = abs(_number(portfolio.get("drawdown")) or 0) if (_number(portfolio.get("drawdown")) or 0) < 0 else (_number(portfolio.get("drawdown")) or 0)
    if daily_loss >= float(rules["halt_daily_loss"]):
        results.append(_rule("daily_loss_halt", "HALT", "组合单日亏损达到熔断阈值", daily_loss, rules["halt_daily_loss"]))
    elif daily_loss >= float(rules["warning_daily_loss"]):
        results.append(_rule("daily_loss_warning", "WARN", "组合单日亏损进入警戒区", daily_loss, rules["warning_daily_loss"]))
    if drawdown >= float(rules["halt_drawdown"]):
        results.append(_rule("drawdown_halt", "HALT", "组合回撤达到熔断阈值", drawdown, rules["halt_drawdown"]))
    elif drawdown >= float(rules["warning_drawdown"]):
        results.append(_rule("drawdown_warning", "WARN", "组合回撤进入警戒区", drawdown, rules["warning_drawdown"]))

    snapshot: dict[str, Any] = {"portfolio": portfolio, "rules": rules}
    if stock_code:
        try:
            latest, rows = _latest_market(stock_code)
            sources = _source_rows(stock_code)
            atr = _atr(rows)
            snapshot.update({"latest_market": latest, "atr": atr, "sources": sources})
            if latest is None:
                results.append(_rule("market_data", "WARN", "缺少最新行情，无法完成完整风控检查", source="trade_stock_daily"))
            elif atr is None:
                results.append(_rule("atr_data", "WARN", "行情历史不足，无法计算 ATR", source="trade_stock_daily"))
            else:
                close = _number(latest.get("close_price")) or 0
                stop_price = close - 2 * atr
                distance = (close - stop_price) / close if close else None
                snapshot["stop_price"] = stop_price
                snapshot["atr_distance"] = distance
                if distance is not None and distance <= float(rules["warning_atr_distance"]):
                    results.append(_rule("atr_stop_distance", "WARN", "价格距离 ATR 止损位较近", distance, rules["warning_atr_distance"], "trade_stock_daily"))
            fear = (sources.get("fear_index") or [None])[0]
            score = _number(fear.get("composite_score")) if fear else None
            if score is None:
                results.append(_rule("macro_data_quality", "WARN", "缺少市场风险指数，宏观门控结果不完整", source="fear_index_history"))
            elif score <= float(rules["macro_halt_score"]):
                results.append(_rule("macro_gate", "HALT", "市场风险处于熔断区间", score, rules["macro_halt_score"], "fear_index_history"))
            elif score <= float(rules["macro_warning_score"]):
                results.append(_rule("macro_gate", "WARN", "市场风险处于警戒区间", score, rules["macro_warning_score"], "fear_index_history"))
            events = sources.get("events") or []
            if action == "buy" and any(str(e.get("signal") or "").lower() in {"negative", "sell", "risk"} for e in events):
                results.append(_rule("material_event", "REJECT", "股票存在近期负面事件", len(events), 0, "market_events"))
            if action == "buy" and any(str(s.get("signal_type") or "").endswith("sell") for s in sources.get("signals") or []):
                results.append(_rule("chan_exit", "WARN", "存在近期缠论卖出或退出信号", source="chan_signals"))
        except Exception as exc:
            results.append(_rule("data_quality", "WARN", f"风险数据读取失败: {type(exc).__name__}"))
    elif action == "buy":
        results.append(_rule("portfolio_data_quality", "WARN", "未提供组合快照，组合级规则无法完整检查", source="request"))

    decision = max((item["decision"] for item in results), key=lambda item: DECISION_ORDER[item], default="APPROVE")
    suggested = target_weight
    for item in results:
        if item["rule"] == "single_weight":
            suggested = min(suggested, float(rules["max_single_weight"])) if suggested is not None else float(rules["max_single_weight"])
    if any(item["rule"] == "macro_gate" and item["decision"] == "WARN" for item in results) and suggested is not None:
        suggested *= 0.5
    risk_level = "high" if decision in {"REJECT", "HALT"} else "medium" if decision == "WARN" else "low"
    snapshot["input"] = payload
    decision_key = hashlib.sha256(json.dumps({"payload": payload, "rules": rules}, sort_keys=True, default=str).encode()).hexdigest()
    result = {"decision": decision, "allowed": decision in {"APPROVE", "WARN"}, "risk_level": risk_level, "suggested_max_weight": suggested, "rules": results, "snapshot": snapshot, "rule_version": "risk-v1", "decision_key": decision_key}
    if persist:
        _persist_decision(result, portfolio_id, stock_code, action)
    return result


def _persist_decision(result: dict[str, Any], portfolio_id: str, stock_code: str, action: str) -> None:
    now = datetime.now()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            portfolio = result["snapshot"].get("portfolio") or {}
            cur.execute("INSERT INTO risk_portfolio_snapshot (portfolio_id, total_assets, cash, holdings_value, total_weight, daily_pnl, daily_pnl_ratio, drawdown, payload_json, snapshot_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (portfolio_id, portfolio.get("total_assets"), portfolio.get("cash"), portfolio.get("holdings_value"), portfolio.get("total_weight"), portfolio.get("daily_pnl"), portfolio.get("daily_pnl_ratio"), portfolio.get("drawdown"), json.dumps(portfolio, ensure_ascii=False, default=str), now))
            cur.execute("INSERT IGNORE INTO risk_decision (decision_key, portfolio_id, stock_code, action, decision, risk_level, suggested_max_weight, rule_results_json, snapshot_json, rule_version, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (result["decision_key"], portfolio_id, stock_code or None, action, result["decision"], result["risk_level"], result["suggested_max_weight"], json.dumps(result["rules"], ensure_ascii=False, default=str), json.dumps(result["snapshot"], ensure_ascii=False, default=str), result["rule_version"], now))
            for item in result["rules"]:
                if item["decision"] != "APPROVE":
                    key = hashlib.sha256(f'{portfolio_id}:{stock_code}:{item["rule"]}:{item["reason"]}'.encode()).hexdigest()
                    cur.execute("INSERT IGNORE INTO risk_alert (alert_key, portfolio_id, stock_code, alert_type, severity, message, value_json, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (key, portfolio_id, stock_code or None, item["rule"], item["decision"], item["reason"], json.dumps(item, ensure_ascii=False, default=str), now))
        conn.commit()
    finally:
        conn.close()


def list_alerts(status: str | None = "active", limit: int = 100) -> list[dict[str, Any]]:
    sql = "SELECT * FROM risk_alert"
    params: list[Any] = []
    if status:
        sql += " WHERE status=%s"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)
    return execute_query(sql, params)


def list_decisions(limit: int = 100) -> list[dict[str, Any]]:
    return execute_query("SELECT * FROM risk_decision ORDER BY created_at DESC LIMIT %s", (limit,))


def acknowledge_alert(alert_id: int) -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            affected = cur.execute("UPDATE risk_alert SET status='acknowledged', acknowledged_at=%s WHERE id=%s AND status='active'", (datetime.now(), alert_id))
        conn.commit()
        return bool(affected)
    finally:
        conn.close()
