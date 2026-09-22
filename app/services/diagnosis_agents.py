"""个股诊断 Agent 层：并行生成结构化结果，再由一次 LLM 调用综合分析。"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

AGENT_TYPES = ("fundamental", "technical", "chan", "factor", "risk", "sentiment")
OPINIONS = {"bullish", "neutral", "bearish"}


def _evidence(source: str, field: str, value: Any, data_as_of: str | None, summary: str) -> dict[str, Any]:
    return {"source": source, "field": field, "value": value, "data_as_of": data_as_of, "summary": summary}


def _result(agent_type: str, opinion: str, score: float | None, confidence: float, summary: str,
            evidence: list[dict[str, Any]], counter_evidence: list[dict[str, Any]], data_as_of: str | None) -> dict[str, Any]:
    return {"agent_type": agent_type, "status": "completed", "opinion": opinion if opinion in OPINIONS else "neutral",
            "score": round(score, 2) if score is not None else None, "confidence": round(max(0, min(1, confidence)), 2),
            "summary": summary, "evidence": evidence, "counter_evidence": counter_evidence,
            "data_as_of": data_as_of, "model_name": "rule-adapter", "prompt_version": "diagnosis-agent-v1",
            "algorithm_version": "diagnosis-agent-v1", "created_at": datetime.now().isoformat()}


def _fundamental(ctx: dict[str, Any]) -> dict[str, Any]:
    value = ctx.get("fundamental") or {}
    score = value.get("score")
    score = float(score) if score is not None else None
    opinion = "bullish" if score is not None and score >= 70 else "bearish" if score is not None and score < 50 else "neutral"
    return _result("fundamental", opinion, score, .8 if score is not None else .25, "基本面指标已完成结构化评估。",
                   [_evidence("trade_stock_financial", "score", score, value.get("report_date"), "基本面综合评分")],
                   [_evidence("trade_stock_financial", "history", len(value.get("history") or []), value.get("report_date"), "历史财务数据样本量")], value.get("report_date"))


def _technical(ctx: dict[str, Any]) -> dict[str, Any]:
    value = ctx.get("technical") or {}
    trend = value.get("trend")
    score = float(value.get("score")) if value.get("score") is not None else None
    opinion = "bullish" if trend == "上升" else "bearish" if trend == "下降" else "neutral"
    return _result("technical", opinion, score, .9 if trend in {"上升", "下降"} else .45, f"技术趋势：{trend or '暂无数据'}。",
                   [_evidence("technical", "trend", trend, value.get("signal_date"), "趋势判断"), _evidence("technical", "score", score, value.get("signal_date"), "技术面评分")],
                   [_evidence("technical", "support", value.get("support"), value.get("signal_date"), "支撑位参考")], value.get("signal_date"))


def _chan(ctx: dict[str, Any]) -> dict[str, Any]:
    value = ctx.get("chan") or {}
    signal = value.get("latest_signal") or {}
    signal_type = signal.get("signal_type") if isinstance(signal, dict) else None
    opinion = "bullish" if signal_type and signal_type.endswith("buy") else "bearish" if signal_type and signal_type.endswith("sell") else "neutral"
    score = float(value.get("score")) if value.get("score") is not None else None
    return _result("chan", opinion, score, .75 if signal_type else .3, value.get("message") or "暂无有效缠论信号。",
                   [_evidence("chan", "signal_type", signal_type, value.get("signal_date"), "最新缠论信号")],
                   [_evidence("chan", "signals", len(value.get("signals") or []), value.get("signal_date"), "已识别信号数量")], value.get("signal_date"))


def _factor(ctx: dict[str, Any]) -> dict[str, Any]:
    value = ctx.get("factor") or {}
    score = float(value.get("score")) if value.get("score") is not None else None
    opinion = "bullish" if score is not None and score >= 70 else "bearish" if score is not None and score < 50 else "neutral"
    return _result("factor", opinion, score, .7 if score is not None else .25, "因子指标已完成综合评分。",
                   [_evidence("factor", "score", score, value.get("data_as_of"), "因子综合评分"), _evidence("factor", "categories", value.get("categories"), value.get("data_as_of"), "因子分类评分")],
                   [_evidence("factor", "factors", value.get("factors"), value.get("data_as_of"), "因子原始指标")], value.get("data_as_of"))


def _risk(ctx: dict[str, Any]) -> dict[str, Any]:
    value = ctx.get("risk") or {}
    level = value.get("level", "medium")
    opinion = "bearish" if level == "high" else "neutral"
    score = 25 if level == "high" else 55 if level == "medium" else 80
    return _result("risk", opinion, score, .85, f"当前风险等级：{level}。",
                   [_evidence("risk", "level", level, ctx.get("data_as_of"), "风险等级")],
                   [_evidence("risk", "items", value.get("items") or [], ctx.get("data_as_of"), "风险事项")], ctx.get("data_as_of"))


def _sentiment(ctx: dict[str, Any]) -> dict[str, Any]:
    snapshot = ctx.get("news_policy") or {}
    summary = snapshot.get("summary") or {}
    direction_map = {"positive": "bullish", "negative": "bearish", "bullish": "bullish", "bearish": "bearish", "neutral": "neutral"}
    opinion = direction_map.get(str(summary.get("direction") or ""), "neutral")
    score = {"bullish": 1, "neutral": 0, "bearish": -1}.get(opinion, 0)
    return _result("sentiment", opinion, score, snapshot.get("confidence", .2), summary.get("text") or "消息面暂无足够证据形成方向判断。", snapshot.get("evidence", []), [], ctx.get("data_as_of"))

_HANDLERS = {"fundamental": _fundamental, "technical": _technical, "chan": _chan, "factor": _factor, "risk": _risk, "sentiment": _sentiment}


def run_agents(context: dict[str, Any], enabled: list[str] | None = None) -> dict[str, dict[str, Any]]:
    names = [name for name in AGENT_TYPES if not enabled or name in enabled]
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(names), thread_name_prefix="diagnosis-agent") as executor:
        futures = {executor.submit(_HANDLERS[name], context): name for name in names}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:  # noqa: BLE001
                results[name] = {"agent_type": name, "status": "failed", "opinion": "neutral", "score": None, "confidence": 0,
                                 "summary": "Agent 执行失败", "evidence": [], "counter_evidence": [], "error_message": str(exc),
                                 "model_name": "rule-adapter", "prompt_version": "diagnosis-agent-v1", "algorithm_version": "diagnosis-agent-v1"}
    return results


def build_debate(agent_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    valid = [item for item in agent_results.values() if item.get("status") == "completed"]
    bulls = [item for item in valid if item.get("opinion") == "bullish"]
    bears = [item for item in valid if item.get("opinion") == "bearish"]
    return {"status": "completed" if len(valid) >= 2 else "skipped", "bull_case": [item.get("summary") for item in bulls],
            "bear_case": [item.get("summary") for item in bears], "disputed_points": [f"多空观点数量：{len(bulls)} 对 {len(bears)}"] if bulls and bears else [],
            "supporting_evidence": [e for item in bulls for e in item.get("evidence", [])],
            "counter_evidence": [e for item in bears for e in item.get("evidence", [])],
            "reason": None if len(valid) >= 2 else "有效 Agent 结果不足两个", "created_at": datetime.now().isoformat()}


def build_consensus(agent_results: dict[str, dict[str, Any]], debate: dict[str, Any]) -> dict[str, Any]:
    """本地降级路径，正常流程使用 build_llm_consensus。"""
    valid = [item for item in agent_results.values() if item.get("status") == "completed" and item.get("score") is not None]
    score = round(sum(float(item["score"]) for item in valid) / len(valid), 2) if valid else None
    bullish = sum(1 for item in valid if item.get("opinion") == "bullish")
    bearish = sum(1 for item in valid if item.get("opinion") == "bearish")
    opinion = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
    confidence = min(1, len(valid) / 6) * (0.8 if bullish and bearish else 1)
    return {"status": "completed" if valid else "unavailable", "opinion": opinion, "score": score, "confidence": round(confidence, 2),
            "supporting_factors": [item.get("summary") for item in valid if item.get("opinion") == "bullish"],
            "risk_factors": [item.get("summary") for item in valid if item.get("opinion") == "bearish"],
            "invalidation_conditions": ["关键数据更新后观点发生反转", "风险等级升至高风险"],
            "conflicts": debate.get("disputed_points", []), "source": "local_fallback",
            "report_version": "2.0", "created_at": datetime.now().isoformat()}


def build_llm_consensus(agent_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """一次性提交六个 Agent 结果，生成多空分析和最终共识。"""
    from app.services.rag_analysis import _llm_chat

    payload = json.dumps(agent_results, ensure_ascii=False, default=str)
    prompt = f"""你是一名股票诊断分析师。请严格基于以下 Agent 结果综合分析，不要编造数据，不要输出 Markdown。识别多空证据和冲突，并给出最终观点。\n\nAgent 结果：\n{payload}\n\n严格输出 JSON：{{\"opinion\":\"bullish|neutral|bearish\",\"score\":0,\"confidence\":0,\"summary\":\"\",\"bull_case\":[],\"bear_case\":[],\"key_evidence\":[],\"risk_factors\":[],\"invalidation_conditions\":[],\"conflicts\":[]}}"""
    text = _llm_chat(prompt).strip()
    if text.startswith("```"):
        text = text.strip("`").split("\\n", 1)[-1]
    result = json.loads(text)
    if result.get("opinion") not in OPINIONS:
        raise ValueError("LLM 返回了无效 opinion")
    result["status"] = "completed"
    result["source"] = "llm"
    result["report_version"] = "3.0"
    result["created_at"] = datetime.now().isoformat()
    return result
