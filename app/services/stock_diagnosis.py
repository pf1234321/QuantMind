"""个股诊断任务、分析器和历史报告服务。"""
from __future__ import annotations

import json
import math
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, List

import numpy as np
import pandas as pd

from app.database import execute_query, execute_update
from app.services.financial_sync import sync_financial
from app.services.diagnosis_agents import AGENT_TYPES, build_consensus, build_debate, build_llm_consensus, run_agents
from app.services.diagnosis_events import detect_events
from app.services.diagnosis_news_policy import build_news_policy_snapshot
from app.services.news_sync import sync_news
from app.services.announcement_sync import query_announcements
from app.services.diagnosis_fundamental_risk import (
    LOOKBACK_ANNOUNCEMENTS,
    LOOKBACK_LIMIT,
    calculate_fundamental_risk,
    to_risk_items,
)
from app.services.diagnosis_risk_reward import build_industry_comparison, calculate_risk_reward
from app.services.rag_analysis import run_five_step_analysis
from app.strategy.signals import detect_chan_signals

MODULES = ("market", "fundamental", "technical", "chan", "factor", "risk")
ANALYSIS_MODULES = ("fundamental", "technical", "chan", "factor")
TERMINAL = {"completed", "partial", "failed", "cancelled", "expired"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _code(value: str) -> str:
    return value.strip().upper().split(".")[0]


def _date(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


class StockDiagnosisService:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="stock-diagnosis")
        self.stage_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="stock-diagnosis-stage")
        self.research_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="stock-diagnosis-research")
        self.futures: dict[str, Future] = {}
        self.cancel_flags: dict[str, threading.Event] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.lock = threading.Lock()

    def search_stocks(self, keyword: str | None, limit: int = 20) -> list[dict[str, Any]]:
        status_sql = (
            "SELECT stock_code, stock_name, sector_1, sector_2, list_date "
            "FROM trade_stock_status"
        )
        if not keyword or not keyword.strip():
            return execute_query(f"{status_sql} ORDER BY stock_code LIMIT %s", (limit,))

        like = f"%{keyword.strip()}%"
        rows = execute_query(
            f"{status_sql} WHERE stock_code LIKE %s OR stock_name LIKE %s "
            "ORDER BY stock_code LIMIT %s",
            (like, like, limit),
        )
        if len(rows) >= limit:
            return rows

        # 财务同步可能先于股票基础数据同步，允许从财务表找到这类股票。
        financial_rows = execute_query(
            "SELECT DISTINCT f.stock_code "
            "FROM trade_stock_financial f "
            "WHERE f.stock_code LIKE %s "
            "AND NOT EXISTS ("
            "SELECT 1 FROM trade_stock_status s WHERE s.stock_code = f.stock_code"
            ") ORDER BY f.stock_code LIMIT %s",
            (like, limit - len(rows)),
        )
        rows.extend(
            {
                "stock_code": item["stock_code"],
                "stock_name": None,
                "sector_1": None,
                "sector_2": None,
                "list_date": None,
            }
            for item in financial_rows
        )
        return rows

    def overview(self, symbol: str) -> dict[str, Any] | None:
        code = _code(symbol)
        rows = execute_query(
            "SELECT stock_code, stock_name, sector_1, sector_2, list_date "
            "FROM trade_stock_status WHERE stock_code=%s LIMIT 1", (code,)
        )
        daily = execute_query(
            "SELECT trade_date, close_price, volume, amount, turnover_rate, "
            "close_price - open_price AS price_change "
            "FROM trade_stock_daily WHERE stock_code=%s AND adjustflag=2 "
            "ORDER BY trade_date DESC LIMIT 2", (code,)
        )
        if not rows and not daily:
            return None
        item: dict[str, Any] = dict(rows[0]) if rows else {"stock_code": code, "stock_name": None}
        latest: dict[str, Any] = dict(daily[0]) if daily else {}
        previous = float(daily[1].get("close_price") or 0) if len(daily) > 1 else 0
        close = float(latest.get("close_price") or 0)
        item.update({"latest": latest, "data_as_of": _date(latest["trade_date"]) if latest.get("trade_date") else None,
                     "change_percent": round((close / previous - 1) * 100, 4) if previous else None,
                     "data_status": "healthy" if daily else "unavailable"})
        return _clean(item)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = _code(payload.get("symbol") or payload.get("stock_code") or "")
        if not symbol:
            raise ValueError("symbol 不能为空")
        modules = [str(item) for item in (payload.get("modules") or MODULES) if str(item) in MODULES]
        if not modules:
            raise ValueError("至少选择一个分析模块")
        periods = [str(item).upper() for item in (payload.get("periods") or ["DAILY", "WEEKLY"])]
        allowed_periods = {"DAILY", "WEEKLY", "60M"}
        if not set(periods) <= allowed_periods:
            raise ValueError("periods 仅支持 DAILY、WEEKLY、60M")
        date_range = payload.get("date_range") or {}
        end = date_range.get("end") or payload.get("end_date") or datetime.now().strftime("%Y-%m-%d")
        start = date_range.get("start") or payload.get("start_date")
        if start and _date(start) > _date(end):
            raise ValueError("开始日期不能晚于结束日期")
        if "60M" in periods:
            raise ValueError("60 分钟数据接口尚未接入，请暂时选择日线或周线")
        if not start:
            start = _date(pd.Timestamp(end) - pd.Timedelta(days=365 * 3))
        overview = self.overview(symbol)
        if not overview or overview.get("data_status") == "unavailable":
            raise ValueError(f"股票 {symbol} 没有可用的前复权行情数据")
        diagnosis_id = str(uuid.uuid4())
        config = {"symbol": symbol, "stock_name": (overview or {}).get("stock_name"), "periods": periods, "modules": modules,
                  "agent_types": [str(item) for item in (payload.get("agent_types") or AGENT_TYPES) if str(item) in AGENT_TYPES],
                  "date_range": {"start": _date(start), "end": _date(end)},
                  "force_refresh": bool(payload.get("force_refresh", False)),
                  "refresh_news": bool(payload.get("refresh_news", True)),
                  "risk_budget": payload.get("risk_budget"),
                  "min_holding_days": payload.get("min_holding_days"),
                  "max_holding_days": payload.get("max_holding_days"),
                  "stop_mode": payload.get("stop_mode") or "atr",
                  "atr_period": payload.get("atr_period"),
                  "atr_multiple": payload.get("atr_multiple"),
                  "trailing_lookback": payload.get("trailing_lookback")}
        now = datetime.now()
        execute_update(
            "INSERT INTO stock_diagnosis_task "
            "(diagnosis_id, stock_code, status, progress, config_json, stage_json, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (diagnosis_id, symbol, "queued", 0, _json(config), _json(self._initial_stages(modules)), now),
        )
        with self.lock:
            self.cancel_flags[diagnosis_id] = threading.Event()
            self.events[diagnosis_id] = []
            self.futures[diagnosis_id] = self.executor.submit(self._execute, diagnosis_id, config)
        return self.get(diagnosis_id) or {"diagnosis_id": diagnosis_id, "status": "queued"}

    @staticmethod
    def _initial_stages(modules: list[str]) -> dict[str, Any]:
        stages = {name: {"status": "queued" if name in modules else "skipped", "progress": 0} for name in MODULES}
        stages.update({"quantitative": {"status": "queued", "progress": 0}, "industry_comparison": {"status": "queued", "progress": 0}, "news_sync": {"status": "queued", "progress": 0}, "news_policy": {"status": "queued", "progress": 0}, "event_analysis": {"status": "queued", "progress": 0}, "agent_analysis": {"status": "queued", "progress": 0}, "debate": {"status": "queued", "progress": 0}, "consensus": {"status": "queued", "progress": 0}, "research_report": {"status": "queued", "progress": 0}, "report": {"status": "queued", "progress": 0}})
        return stages

    def _emit(self, diagnosis_id: str, event_type: str, **data: Any) -> None:
        event = {"type": event_type, "diagnosis_id": diagnosis_id, "at": datetime.now().isoformat(), **_clean(data)}
        with self.lock:
            self.events.setdefault(diagnosis_id, []).append(event)

    def _update(self, diagnosis_id: str, *, status: str | None = None, progress: int | None = None,
                stage: str | None = None, stages: dict[str, Any] | None = None, report: dict[str, Any] | None = None,
                error: str | None = None) -> None:
        fields: list[str] = []
        values: list[Any] = []
        if status is not None:
            fields.append("status=%s"); values.append(status)
        if progress is not None:
            fields.append("progress=%s"); values.append(progress)
        if stage is not None:
            fields.append("current_stage=%s"); values.append(stage)
        if stages is not None:
            fields.append("stage_json=%s"); values.append(_json(stages))
        if report is not None:
            fields.append("report_json=%s"); values.append(_json(report))
        if error is not None:
            fields.append("error_message=%s"); values.append(error)
        if status == "running":
            fields.append("started_at=COALESCE(started_at,%s)"); values.append(datetime.now())
        if status in TERMINAL:
            fields.append("finished_at=%s"); values.append(datetime.now())
        if fields:
            values.append(diagnosis_id)
            execute_update(f"UPDATE stock_diagnosis_task SET {', '.join(fields)} WHERE diagnosis_id=%s", values)

    def _execute(self, diagnosis_id: str, config: dict[str, Any]) -> None:
        stages = self._initial_stages(config["modules"])
        results: dict[str, Any] = {}
        try:
            self._update(diagnosis_id, status="running", progress=1, stage="market", stages=stages)
            self._emit(diagnosis_id, "diagnosis.started", progress=1)
            market = self._market(config)
            results["market"] = market
            stages["market"] = {"status": "completed", "progress": 100, "result": market}
            self._update(diagnosis_id, progress=10, stage="analysis", stages=stages)
            selected = [name for name in ANALYSIS_MODULES if name in config["modules"]]
            futures = {name: self.stage_executor.submit(self._run_stage, name, config, diagnosis_id) for name in selected}
            errors: dict[str, str] = {}
            for name, future in futures.items():
                if self.cancel_flags[diagnosis_id].is_set():
                    raise InterruptedError("用户取消诊断任务")
                try:
                    results[name] = future.result()
                    stages[name] = {"status": "completed", "progress": 100, "result": results[name]}
                except Exception as exc:  # noqa: BLE001
                    errors[name] = str(exc)
                    stages[name] = {"status": "failed", "progress": 100, "error": str(exc)}
                done = sum(1 for item in stages.values() if item.get("status") == "completed")
                progress = min(90, 10 + int(done / max(len(selected), 1) * 75))
                self._update(diagnosis_id, progress=progress, stage=name, stages=stages)
                self._emit(diagnosis_id, "diagnosis.stage.completed" if name not in errors else "diagnosis.stage.failed", stage=name, progress=progress)
            if "risk" in config["modules"]:
                if not config.get("stock_name"):
                    status_rows = execute_query(
                        "SELECT stock_name FROM trade_stock_status WHERE stock_code=%s LIMIT 1",
                        (config["symbol"],),
                    )
                    if status_rows:
                        config["stock_name"] = status_rows[0].get("stock_name")
                results["risk"] = self._risk(results, config)
                stages["risk"] = {"status": "completed", "progress": 100, "result": results["risk"]}
            stages["quantitative"] = {"status": "running", "progress": 0}
            self._update(diagnosis_id, progress=88, stage="quantitative", stages=stages)
            try:
                results["risk_reward"] = calculate_risk_reward(results.get("market") or {}, results.get("technical") or {}, config)
                stages["quantitative"] = {"status": "completed", "progress": 100, "result": results["risk_reward"]}
            except Exception as exc:  # noqa: BLE001
                errors["quantitative"] = str(exc)
                stages["quantitative"] = {"status": "failed", "progress": 100, "error": str(exc)}
            stages["industry_comparison"] = {"status": "running", "progress": 0}
            try:
                status_rows = execute_query("SELECT stock_code, stock_name, sector_1, sector_2, sector_3 FROM trade_stock_status WHERE stock_code=%s LIMIT 1", (config["symbol"],))
                stock_status = status_rows[0] if status_rows else {}
                sector = stock_status.get("sector_2") or stock_status.get("sector_1")
                peer_rows = execute_query("SELECT stock_code, stock_name, sector_1, sector_2, sector_3 FROM trade_stock_status WHERE sector_2=%s OR (sector_2 IS NULL AND sector_1=%s) LIMIT 20", (sector, sector)) if sector else []
                results["industry_comparison"] = build_industry_comparison(config["symbol"], stock_status, peer_rows)
                stages["industry_comparison"] = {"status": "completed", "progress": 100, "result": results["industry_comparison"]}
            except Exception as exc:  # noqa: BLE001
                errors["industry_comparison"] = str(exc)
                stages["industry_comparison"] = {"status": "failed", "progress": 100, "error": str(exc)}
            if config.get("refresh_news", True):
                stages["news_sync"] = {"status": "running", "progress": 0}
                self._update(diagnosis_id, progress=89, stage="news_sync", stages=stages)
                try:
                    stock_name = config.get("stock_name") or config["symbol"]
                    results["news_sync"] = sync_news([(config["symbol"], stock_name)])
                    stages["news_sync"] = {"status": "completed", "progress": 100, "result": results["news_sync"]}
                except Exception as exc:  # noqa: BLE001
                    errors["news_sync"] = str(exc)
                    results["news_sync"] = {"status": "failed", "error": str(exc)}
                    stages["news_sync"] = {"status": "failed", "progress": 100, "error": str(exc)}
            else:
                stages["news_sync"] = {"status": "skipped", "progress": 100}

            stages["news_policy"] = {"status": "running", "progress": 0}
            self._update(diagnosis_id, progress=90, stage="news_policy", stages=stages)
            agent_context = dict(results)
            agent_context["data_as_of"] = (results.get("market") or {}).get("data_as_of")
            try:
                results["news_policy"] = build_news_policy_snapshot(config["symbol"], agent_context["data_as_of"])
                stages["news_policy"] = {"status": results["news_policy"].get("status", "completed"), "progress": 100, "result": results["news_policy"]}
                stages["event_analysis"] = {"status": "running", "progress": 0}
                results["events"] = detect_events(config["symbol"], agent_context["data_as_of"], diagnosis_id)
                stages["event_analysis"] = {"status": "completed", "progress": 100, "result": results["events"]}
            except Exception as exc:  # noqa: BLE001
                errors["news_policy"] = str(exc)
                results["news_policy"] = {"status": "failed", "error": str(exc)}
                stages["news_policy"] = {"status": "failed", "progress": 100, "error": str(exc)}
                stages["event_analysis"] = {"status": "failed", "progress": 100, "error": str(exc)}
            agent_context["news_policy"] = results["news_policy"]
            agent_results = run_agents(agent_context, config.get("agent_types"))
            stages["agent_analysis"] = {"status": "completed", "progress": 100, "result": agent_results}
            self._update(diagnosis_id, progress=94, stage="agent_analysis", stages=stages)
            self._emit(diagnosis_id, "diagnosis.agent.completed", progress=94, agents=list(agent_results))
            try:
                consensus = build_llm_consensus(agent_results)
                debate = {
                    "status": "completed",
                    "bull_case": consensus.get("bull_case", []),
                    "bear_case": consensus.get("bear_case", []),
                    "disputed_points": consensus.get("conflicts", []),
                    "supporting_evidence": consensus.get("key_evidence", []),
                    "counter_evidence": consensus.get("risk_factors", []),
                    "source": "llm",
                    "created_at": datetime.now().isoformat(),
                }
            except Exception as exc:  # noqa: BLE001
                errors["llm_consensus"] = str(exc)
                consensus = build_consensus(agent_results, build_debate(agent_results))
                consensus["status"] = "llm_failed"
                consensus["error"] = str(exc)
                debate = build_debate(agent_results)
                debate["source"] = "local_fallback"
            stages["debate"] = {"status": "completed" if debate.get("status") == "completed" else "skipped", "progress": 100, "result": debate}
            stages["consensus"] = {"status": "completed" if consensus.get("status") == "completed" else "skipped", "progress": 100, "result": consensus}
            results["agent_analysis"] = agent_results
            results["debate"] = debate
            results["consensus"] = consensus
            self._persist_agent_snapshot(diagnosis_id, agent_results, debate, consensus)
            self._persist_quant_snapshot(diagnosis_id, results.get("risk_reward"), results.get("industry_comparison"))
            data_as_of = (results.get("market") or {}).get("data_as_of")
            stages["research_report"] = {"status": "running", "progress": 0}
            self._update(diagnosis_id, progress=96, stage="research_report", stages=stages)
            try:
                research_future = self.research_executor.submit(
                    run_five_step_analysis, config["symbol"], config.get("stock_name"), end_date=data_as_of
                )
                # 五步法包含 5 次串行 LLM 请求，每次客户端最长等待 180 秒；
                # 这里不能使用小于单次请求上限的总超时，否则正常请求必然被提前判定为超时。
                results["research"] = research_future.result(timeout=900)
                results["research"]["status"] = "completed"
                results["research"]["data_as_of"] = data_as_of
                stages["research_report"] = {"status": "completed", "progress": 100, "result": results["research"]}
            except TimeoutError:
                errors["research_report"] = "五步法分析超时，已跳过，不影响基础诊断结果"
                results["research"] = {"status": "timeout", "error": errors["research_report"], "data_as_of": data_as_of}
                stages["research_report"] = {"status": "timeout", "progress": 100, "error": errors["research_report"]}
            except Exception as exc:  # noqa: BLE001
                errors["research_report"] = str(exc)
                results["research"] = {"status": "failed", "error": str(exc), "data_as_of": data_as_of}
                stages["research_report"] = {"status": "failed", "progress": 100, "error": str(exc)}
            self._update(diagnosis_id, progress=99, stage="research_report", stages=stages)
            report = self._report(config, results, errors)
            final = "completed" if not errors else "partial" if results else "failed"
            stages["report"] = {"status": "completed", "progress": 100}
            self._update(diagnosis_id, status=final, progress=100, stage="report", stages=stages, report=report,
                         error="；".join(f"{k}: {v}" for k, v in errors.items()) if errors else None)
            self._emit(diagnosis_id, "diagnosis.completed", status=final, progress=100)
        except InterruptedError as exc:
            self._update(diagnosis_id, status="cancelled", progress=100, stage="cancelled", stages=stages, error=str(exc))
            self._emit(diagnosis_id, "diagnosis.cancelled", progress=100)
        except Exception as exc:  # noqa: BLE001
            self._update(diagnosis_id, status="failed", progress=100, stage="failed", stages=stages, error=str(exc))
            self._emit(diagnosis_id, "diagnosis.failed", error=str(exc), progress=100)

    def _run_stage(self, name: str, config: dict[str, Any], diagnosis_id: str) -> dict[str, Any]:
        self._emit(diagnosis_id, "diagnosis.stage.started", stage=name)
        if name == "fundamental": return self._fundamental(config)
        if name == "technical": return self._technical(config)
        if name == "chan": return self._chan(config)
        return self._factor(config)

    def _daily(self, config: dict[str, Any], limit: int = 2000) -> pd.DataFrame:
        rows = execute_query(
            "SELECT trade_date, open_price AS open, high_price AS high, low_price AS low, "
            "close_price AS close, volume, amount, turnover_rate FROM trade_stock_daily "
            "WHERE stock_code=%s AND adjustflag=2 AND trade_date BETWEEN %s AND %s "
            "ORDER BY trade_date", (config["symbol"], config["date_range"]["start"], config["date_range"]["end"]),
        )
        frame = pd.DataFrame(rows)
        if frame.empty:
            raise ValueError("前复权行情数据为空")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        for col in ("open", "high", "low", "close", "volume", "amount", "turnover_rate"):
            if col in frame: frame[col] = pd.to_numeric(frame[col], errors="coerce")
        return frame.dropna(subset=["open", "high", "low", "close"]).tail(limit).reset_index(drop=True)

    def _market(self, config: dict[str, Any]) -> dict[str, Any]:
        frame = self._daily(config)
        last = frame.iloc[-1]
        previous = frame.iloc[-2] if len(frame) > 1 else last
        series = frame.tail(120)[["trade_date", "open", "high", "low", "close", "volume"]].to_dict("records")
        return {"symbol": config["symbol"], "signal_date": _date(last.trade_date), "data_as_of": _date(last.trade_date),
                "close": float(last.close), "change_percent": round((float(last.close) / float(previous.close) - 1) * 100, 4) if previous.close else None,
                "volume": float(last.volume or 0),                 "amount": float(last.amount or 0), "turnover_rate": _clean(last.get("turnover_rate")),
                "data_source": "trade_stock_daily", "adjustflag": 2, "series": _clean(series), "data_window": len(frame)}

    @staticmethod
    def _financial_detail_ready(rows: list[dict[str, Any]]) -> bool:
        """至少有 4 期记录，且最近 4 期的明细指标覆盖率达到一半。"""
        if len(rows) < 4:
            return False
        detail_fields = ("roa", "net_margin", "debt_ratio", "current_ratio", "operating_cashflow", "total_assets", "total_equity")
        available = sum(1 for row in rows[:4] for field in detail_fields if row.get(field) is not None)
        return available >= len(detail_fields) * 2

    def _fundamental(self, config: dict[str, Any]) -> dict[str, Any]:
        symbol = config["symbol"]
        query = (
            "SELECT report_date, revenue, net_profit, eps, roe, roa, gross_margin, net_margin, debt_ratio, "
            "current_ratio, operating_cashflow, total_assets, total_equity, data_source "
            "FROM trade_stock_financial WHERE stock_code=%s ORDER BY report_date DESC LIMIT 8"
        )
        rows = execute_query(query, (symbol,))
        detail_refreshed = False
        detail_reason = None
        if not self._financial_detail_ready(rows):
            try:
                sync_result = sync_financial(stock_codes=[symbol], quarters=4, enrich_detail=True)
                detail_refreshed = True
                detail_reason = sync_result
                rows = execute_query(query, (symbol,))
            except Exception as exc:  # noqa: BLE001
                detail_reason = f"财务明细补全失败: {exc}"
        if not rows:
            raise ValueError(detail_reason or "未找到财务数据")
        latest = dict(rows[0])
        fields = ["revenue", "net_profit", "eps", "roe", "roa", "gross_margin", "net_margin", "debt_ratio", "current_ratio", "operating_cashflow", "total_assets", "total_equity"]
        metrics = {field: {"value": latest.get(field), "data_date": _date(latest["report_date"]), "source": latest.get("data_source") or "trade_stock_financial"} for field in fields}
        score_parts = [float(latest[x]) for x in ("roe", "roa", "gross_margin") if latest.get(x) is not None]
        status = "healthy" if self._financial_detail_ready(rows) else "partial"
        result = {"report_date": _date(latest["report_date"]), "metrics": _clean(metrics), "history": _clean(rows),
                  "score": round(min(100, max(0, 50 + (np.mean(score_parts) if score_parts else 0))), 2),
                  "status": status, "data_source": "trade_stock_financial", "detail_refreshed": detail_refreshed}
        if detail_reason:
            result["detail_sync"] = _clean(detail_reason)
        return result

    def _technical(self, config: dict[str, Any]) -> dict[str, Any]:
        frame = self._daily(config, 5000)
        close, volume = frame.close, frame.volume
        for period in (5, 10, 20, 60, 120): frame[f"ma{period}"] = close.rolling(period).mean()
        delta = close.diff(); gain = delta.clip(lower=0).rolling(14).mean(); loss = -delta.clip(upper=0).rolling(14).mean()
        frame["rsi14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        ema12, ema26 = close.ewm(span=12, adjust=False).mean(), close.ewm(span=26, adjust=False).mean()
        frame["dif"] = ema12 - ema26; frame["dea"] = frame.dif.ewm(span=9, adjust=False).mean(); frame["macd"] = (frame.dif - frame.dea) * 2
        frame["volume_ratio"] = volume / volume.rolling(20).mean()
        latest = frame.iloc[-1]
        keys = ["ma5", "ma10", "ma20", "ma60", "ma120", "rsi14", "dif", "dea", "macd", "volume_ratio"]
        metrics = {key: _clean(latest.get(key)) for key in keys}
        trend = "上升" if latest.close > latest.ma20 and latest.ma20 > latest.ma60 else "下降" if latest.close < latest.ma20 else "震荡"
        series = frame.tail(120)[["trade_date", "open", "high", "low", "close", "volume", *keys]].to_dict("records")
        return {"signal_date": _date(latest.trade_date), "metrics": metrics, "trend": trend,
                "momentum": "增强" if latest.macd > 0 else "减弱", "support": _clean(frame.low.tail(20).min()),
                "resistance": _clean(frame.high.tail(20).max()), "series": _clean(series), "score": 70 if trend == "上升" else 40}

    def _chan(self, config: dict[str, Any]) -> dict[str, Any]:
        frame = self._daily(config, 5000).set_index("trade_date")
        signals = detect_chan_signals(frame[["open", "high", "low", "close"]], config["symbol"], frame.index[-1])
        return {"signal_date": _date(frame.index[-1]), "signals": _clean(signals[-20:]),
                "latest_signal": _clean(signals[-1]) if signals else None,
                "message": "当前未识别到有效缠论买卖点" if not signals else "已识别有效缠论信号",
                "score": 70 if signals and signals[-1]["signal_type"].endswith("buy") else 50}

    def _factor(self, config: dict[str, Any]) -> dict[str, Any]:
        technical = self._technical(config)
        metrics = technical["metrics"]
        values = {"momentum": metrics.get("ma20"), "volatility": metrics.get("rsi14"), "volume": metrics.get("volume_ratio")}
        score = 60
        if technical["trend"] == "上升": score += 15
        if technical["momentum"] == "增强": score += 10
        return {"factor_version": "diagnosis-v1", "factors": _clean(values), "categories": {"估值": None, "成长": None, "盈利质量": None, "动量": score, "波动率": metrics.get("rsi14"), "流动性": metrics.get("volume_ratio")}, "score": min(score, 100), "data_as_of": technical["signal_date"]}

    def _announcements(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        end = config.get("date_range", {}).get("end")
        start = _date(pd.Timestamp(end) - pd.Timedelta(days=LOOKBACK_ANNOUNCEMENTS)) if end else None
        try:
            return query_announcements(config["symbol"], start_date=start, end_date=end, limit=LOOKBACK_LIMIT)
        except Exception:  # noqa: BLE001
            return []

    def _risk(self, results: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        config = config or {}
        risks = []
        technical = results.get("technical") or {}
        if technical.get("trend") == "下降":
            risks.append({"type": "trend_weak", "level": "high", "source": "technical", "description": "价格位于主要均线下方"})
        fundamental_risk = calculate_fundamental_risk(
            results.get("fundamental"),
            stock_name=config.get("stock_name"),
            announcements=self._announcements(config),
        )
        risks.extend(to_risk_items(fundamental_risk))
        level = "high" if any(item["level"] == "high" for item in risks) else "medium" if risks else "low"
        return {
            "level": level,
            "items": risks,
            "fundamental_score": fundamental_risk.get("score"),
            "fundamental_level": fundamental_risk.get("level"),
            "fundamental_tags": fundamental_risk.get("tags") or [],
            "fundamental_categories": fundamental_risk.get("categories") or {},
            "rule_version": fundamental_risk.get("rule_version"),
        }

    def _report(self, config: dict[str, Any], results: dict[str, Any], errors: dict[str, str]) -> dict[str, Any]:
        scores = [item.get("score") for item in results.values() if isinstance(item, dict) and item.get("score") is not None]
        market = results.get("market") or {}
        return {"symbol": config["symbol"], "signal_date": market.get("signal_date"), "data_as_of": market.get("data_as_of"),
                "summary": {"score": round(float(np.mean(scores)), 2) if scores else None, "trend": (results.get("technical") or {}).get("trend"), "confidence": round(len(scores) / 4, 2)},
                "sections": _clean(results), "errors": errors, "data_quality": {"status": "warning" if errors else "healthy", "issues": list(errors.values())},
                "algorithm_version": "stock-diagnosis-v1", "report_version": "3.0", "sentiment": _clean(results.get("news_policy")), "policy": _clean((results.get("news_policy") or {}).get("policy")), "research": _clean(results.get("research")),
                "agent_analysis": _clean(results.get("agent_analysis")), "debate": _clean(results.get("debate")), "consensus": _clean(results.get("consensus")),
                "risk_reward": _clean(results.get("risk_reward")), "industry_comparison": _clean(results.get("industry_comparison")),
                "disclaimer": "本报告仅供研究辅助，不构成投资建议；系统不会自动下单或修改持仓。"}

    def _persist_agent_snapshot(self, diagnosis_id: str, agent_results: dict[str, Any], debate: dict[str, Any], consensus: dict[str, Any]) -> None:
        run_id = str(uuid.uuid4())
        for agent_type, result in agent_results.items():
            execute_update(
                "INSERT INTO diagnosis_agent_result (run_id, diagnosis_id, agent_type, status, result_json, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (run_id, diagnosis_id, agent_type, result.get("status", "failed"), _json(result), datetime.now()),
            )
        execute_update("INSERT INTO diagnosis_debate (run_id, diagnosis_id, result_json, created_at) VALUES (%s,%s,%s,%s)", (run_id, diagnosis_id, _json(debate), datetime.now()))
        execute_update("INSERT INTO diagnosis_consensus (run_id, diagnosis_id, result_json, created_at) VALUES (%s,%s,%s,%s)", (run_id, diagnosis_id, _json(consensus), datetime.now()))

    def _persist_quant_snapshot(self, diagnosis_id: str, risk_reward: dict[str, Any] | None, industry: dict[str, Any] | None) -> None:
        run_id = str(uuid.uuid4())
        for module, result in (("risk_reward", risk_reward), ("industry_comparison", industry)):
            if result is None:
                continue
            execute_update(
                "INSERT INTO diagnosis_quant_result (diagnosis_id, run_id, module, status, result_json, input_fingerprint, rule_version, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (diagnosis_id, run_id, module, result.get("status", "unavailable"), _json(result), result.get("input_fingerprint"), result.get("rule_version"), datetime.now()),
            )

    def quant_result(self, diagnosis_id: str, module: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM diagnosis_quant_result WHERE diagnosis_id=%s"
        params: list[Any] = [diagnosis_id]
        if module:
            query += " AND module=%s"
            params.append(module)
        query += " ORDER BY created_at DESC, id DESC"
        rows = execute_query(query, tuple(params))
        for row in rows:
            if row.get("result_json"):
                try: row["result"] = json.loads(row["result_json"])
                except (TypeError, json.JSONDecodeError): pass
        return _clean(rows)

    def agent_results(self, diagnosis_id: str) -> list[dict[str, Any]]:
        rows = execute_query("SELECT * FROM diagnosis_agent_result WHERE diagnosis_id=%s ORDER BY created_at, id", (diagnosis_id,))
        for row in rows:
            if row.get("result_json"):
                try: row["result"] = json.loads(row["result_json"])
                except (TypeError, json.JSONDecodeError): pass
        return _clean(rows)

    def debate(self, diagnosis_id: str) -> dict[str, Any] | None:
        rows = execute_query("SELECT * FROM diagnosis_debate WHERE diagnosis_id=%s ORDER BY created_at DESC LIMIT 1", (diagnosis_id,))
        return _clean(json.loads(rows[0]["result_json"])) if rows and rows[0].get("result_json") else None

    def consensus(self, diagnosis_id: str) -> dict[str, Any] | None:
        rows = execute_query("SELECT * FROM diagnosis_consensus WHERE diagnosis_id=%s ORDER BY created_at DESC LIMIT 1", (diagnosis_id,))
        return _clean(json.loads(rows[0]["result_json"])) if rows and rows[0].get("result_json") else None

    def get(self, diagnosis_id: str) -> dict[str, Any] | None:
        rows = execute_query("SELECT * FROM stock_diagnosis_task WHERE diagnosis_id=%s", (diagnosis_id,))
        if not rows: return None
        row = dict(rows[0])
        for field in ("config_json", "stage_json", "report_json"):
            if row.get(field):
                try: row[field.removesuffix("_json")] = json.loads(row[field])
                except (TypeError, json.JSONDecodeError): pass
        return _clean(row)

    def list(self, symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if symbol:
            rows = execute_query("SELECT diagnosis_id, stock_code, status, progress, current_stage, created_at, finished_at FROM stock_diagnosis_task WHERE stock_code=%s ORDER BY created_at DESC LIMIT %s", (_code(symbol), limit))
        else:
            rows = execute_query("SELECT diagnosis_id, stock_code, status, progress, current_stage, created_at, finished_at FROM stock_diagnosis_task ORDER BY created_at DESC LIMIT %s", (limit,))
        return _clean([dict(row) for row in rows])

    def cancel(self, diagnosis_id: str) -> dict[str, Any] | None:
        result = self.get(diagnosis_id)
        if not result: return None
        if result.get("status") not in TERMINAL:
            self.cancel_flags.setdefault(diagnosis_id, threading.Event()).set()
            self._update(diagnosis_id, status="cancelled", progress=100, stage="cancelled", error="用户取消诊断任务")
        return self.get(diagnosis_id)

    def events_since(self, diagnosis_id: str, offset: int = 0) -> tuple[List[dict[str, Any]], int]:
        with self.lock:
            events: list[dict[str, Any]] = list(self.events.get(diagnosis_id, []))
        return events[offset:], len(events)

    def retry(self, diagnosis_id: str) -> dict[str, Any] | None:
        result = self.get(diagnosis_id)
        if not result: return None
        config = result.get("config") or {}
        failed = [name for name, stage in (result.get("stage") or {}).items() if stage.get("status") == "failed"]
        if not failed: return result
        config["modules"] = failed
        return self.create(config)


service = StockDiagnosisService()


def init_stock_diagnosis_schema() -> None:
    execute_update("""
        CREATE TABLE IF NOT EXISTS stock_diagnosis_task (
            diagnosis_id VARCHAR(64) NOT NULL PRIMARY KEY,
            stock_code VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL,
            progress INT NOT NULL DEFAULT 0,
            current_stage VARCHAR(40) NULL,
            config_json JSON NOT NULL,
            stage_json JSON NOT NULL,
            report_json JSON NULL,
            error_message TEXT NULL,
            created_at DATETIME NOT NULL,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            KEY idx_stock_diagnosis_stock (stock_code, created_at),
            KEY idx_stock_diagnosis_status (status, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_update("""
        CREATE TABLE IF NOT EXISTS diagnosis_quant_result (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            diagnosis_id VARCHAR(64) NOT NULL,
            run_id VARCHAR(64) NOT NULL,
            module VARCHAR(40) NOT NULL,
            status VARCHAR(20) NOT NULL,
            result_json JSON NOT NULL,
            input_fingerprint VARCHAR(64) NULL,
            rule_version VARCHAR(40) NULL,
            created_at DATETIME NOT NULL,
            KEY idx_quant_diagnosis (diagnosis_id, created_at),
            KEY idx_quant_run (run_id, module)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_update("""
        CREATE TABLE IF NOT EXISTS diagnosis_agent_result (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            run_id VARCHAR(64) NOT NULL,
            diagnosis_id VARCHAR(64) NOT NULL,
            agent_type VARCHAR(40) NOT NULL,
            status VARCHAR(20) NOT NULL,
            result_json JSON NOT NULL,
            created_at DATETIME NOT NULL,
            KEY idx_agent_diagnosis (diagnosis_id, created_at),
            KEY idx_agent_run (run_id, agent_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_update("""
        CREATE TABLE IF NOT EXISTS diagnosis_debate (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            run_id VARCHAR(64) NOT NULL,
            diagnosis_id VARCHAR(64) NOT NULL,
            result_json JSON NOT NULL,
            created_at DATETIME NOT NULL,
            KEY idx_debate_diagnosis (diagnosis_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_update("""
        CREATE TABLE IF NOT EXISTS diagnosis_consensus (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            run_id VARCHAR(64) NOT NULL,
            diagnosis_id VARCHAR(64) NOT NULL,
            result_json JSON NOT NULL,
            created_at DATETIME NOT NULL,
            KEY idx_consensus_diagnosis (diagnosis_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

