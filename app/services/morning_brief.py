"""晨会分析：板块轮动 -> 多因子选股 -> 报告 -> 推送。"""
from __future__ import annotations

import html
import json
import logging
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from app.config import settings
from app.database import execute_query

logger = logging.getLogger("quantmind.morning_brief")
NODE_ORDER = ["industry", "stock_picker", "report", "push"]
NODE_LABELS = {
    "industry": "板块强度",
    "stock_picker": "多因子选股",
    "report": "晨报生成",
    "push": "晨报推送",
}
PHASE_DESC = {"accel_up": "主升加速", "decel_up": "高位钝化", "accel_down": "主跌", "decel_down": "左侧抄底", "neutral": "中性"}
RUN_LOCK = threading.Lock()
CACHE_DIR = settings.DATA_DIR / "cache"
REPORT_DIR = settings.DATA_DIR / "reports" / "morning"
LATEST_CACHE = CACHE_DIR / "morning_latest.json"


def _ensure_kline_data_synced(emit: Callable[[str, dict[str, Any]], None] | None = None) -> None:
    """确保K线数据同步到最新的交易日"""
    from app.services.kline_sync import sync_kline

    try:
        # 检查K线数据最新日期
        latest = execute_query("SELECT MAX(trade_date) AS latest FROM trade_stock_daily")
        latest_date = latest[0]['latest'] if latest and latest[0]['latest'] else None

        today = date.today()

        if latest_date and (today - latest_date).days <= 1:
            logger.info(f"K线数据已是最新 (截止: {latest_date})")
            if emit:
                emit("sync_skip", {"message": f"K线数据已是最新 (截止: {latest_date})", "latest_date": str(latest_date)})
            return

        # 获取需要同步的股票列表（限制100只，避免阻塞太久）
        stocks = execute_query("""
            SELECT stock_code
            FROM trade_stock_status
            WHERE status = 1
            LIMIT 100
        """)

        if not stocks:
            logger.warning("未找到需要同步的股票列表")
            return

        stock_codes = [s['stock_code'] for s in stocks]

        # 增量同步K线数据
        start_date = (latest_date + timedelta(days=1)).strftime('%Y%m%d') if latest_date else None
        end_date = today.strftime('%Y%m%d')

        logger.info(f"开始同步K线数据: {len(stock_codes)} 只股票, 从 {start_date} 到 {end_date}")
        if emit:
            emit("sync_progress", {"message": f"正在同步 {len(stock_codes)} 只股票的K线数据...", "count": len(stock_codes)})

        result = sync_kline(stock_codes=stock_codes, start_date=start_date, end_date=end_date)
        logger.info(f"K线数据同步完成: {result}")

        if emit:
            emit("sync_complete", {"message": f"K线数据同步完成", "result": str(result)})

    except Exception as e:
        logger.error(f"K线数据同步失败: {e}", exc_info=True)
        if emit:
            emit("sync_error", {"message": f"K线数据同步失败: {str(e)}"})
        # 同步失败不阻断晨会分析流程，继续使用现有数据


def _json_value(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _round(value: Any, digits: int = 4) -> float | None:
    try:
        number = float(value)
        return round(number, digits) if np.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "top_industries": min(10, max(1, int(params.get("top_industries", 3)))),
        "top_stocks": min(20, max(1, int(params.get("top_stocks", 5)))),
        "sample_per_industry": min(50, max(5, int(params.get("sample_per_industry", 15)))),
        "lookback": min(250, max(60, int(params.get("lookback", 90)))),
        "industry_level": min(2, max(1, int(params.get("industry_level", 2)))),
        "enable_push": bool(params.get("enable_push", True)),
    }


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=1)
    return (series - series.mean()) / std if pd.notna(std) and std > 0 else pd.Series(0.0, index=series.index)


def _phase(close: pd.Series) -> tuple[str, str]:
    if len(close) < 65:
        return "neutral", PHASE_DESC["neutral"]
    roc = (close.iloc[-1] / close.iloc[-21] - 1) * 100
    ma = close.rolling(20).mean()
    slope = (ma.iloc[-1] / ma.iloc[-6] - 1) * 100 if ma.iloc[-6] else 0
    hist = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    hist_delta = hist.iloc[-1] - hist.iloc[-2]
    if roc > 0.5 and slope > 0.1 and hist.iloc[-1] > 0 and hist_delta > 0:
        key = "accel_up"
    elif roc > 0.5 and slope > 0.1 and hist_delta < 0:
        key = "decel_up"
    elif roc < -0.5 and slope < -0.1 and hist.iloc[-1] < 0 and hist_delta < 0:
        key = "accel_down"
    elif roc < -0.5 and slope < -0.1 and hist_delta > 0:
        key = "decel_down"
    else:
        key = "neutral"
    return key, PHASE_DESC[key]


def _load_industries(level: int, lookback: int, end_date: str | None = None) -> list[dict[str, Any]]:
    end = end_date or str(date.today())
    start = str(pd.to_datetime(end) - timedelta(days=max(lookback * 2, 140)))[:10]
    try:
        rows = execute_query(
            "SELECT sector_name, trade_date, close_idx, total_amount, stock_count "
            "FROM trade_sector_daily WHERE sector_level=%s AND trade_date BETWEEN %s AND %s ORDER BY trade_date ASC",
            (level, start, end),
        )
    except Exception:
        # QuantMind 默认未维护教程项目的板块日线表，回退到个股日线聚合行业指数。
        industry_field = "sector_1" if level == 1 else "sector_2"
        rows = execute_query(
            f"SELECT s.{industry_field} AS sector_name, d.trade_date, "
            "AVG(d.close_price) AS close_idx, SUM(d.amount) AS total_amount, "
            "COUNT(DISTINCT d.stock_code) AS stock_count "
            "FROM trade_stock_daily d JOIN trade_stock_status s ON s.stock_code=d.stock_code "
            f"WHERE d.adjustflag=2 AND s.{industry_field} IS NOT NULL AND d.trade_date BETWEEN %s AND %s "
            f"GROUP BY s.{industry_field}, d.trade_date ORDER BY d.trade_date ASC",
            (start, end),
        )
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    for col in ["close_idx", "total_amount", "stock_count"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    rows_out: list[dict[str, Any]] = []
    grouped = frame.dropna(subset=["sector_name"]).groupby("sector_name")
    for name, group in grouped:
        group = group.sort_values("trade_date").tail(max(lookback, 70))
        close = group["close_idx"].dropna()
        amount = group["total_amount"].fillna(0)
        if len(close) < 65:
            continue
        mom = close.iloc[-1] / close.iloc[-22] - 1 if len(close) >= 22 and close.iloc[-22] else np.nan
        rs = mom
        vol = amount.tail(5).mean() / amount.tail(60).mean() if amount.tail(60).mean() > 0 else np.nan
        roc20 = close.iloc[-1] / close.iloc[-21] - 1 if len(close) >= 21 and close.iloc[-21] else np.nan
        phase, phase_desc = _phase(close)
        rows_out.append({"industry": name, "MOM_21": _round(mom), "RS_60": _round(rs), "VOL_R": _round(vol), "ROC_20": _round(roc20 * 100 if pd.notna(roc20) else np.nan, 2), "phase": phase, "phase_desc": phase_desc, "members": int(group["stock_count"].iloc[-1] or 0), "data_as_of": str(group["trade_date"].iloc[-1].date())})
    result = pd.DataFrame(rows_out)
    if result.empty:
        return []
    for col in ["MOM_21", "RS_60", "VOL_R"]:
        result[f"_{col}"] = _zscore(result[col].astype(float))
    result["score"] = result["_MOM_21"] + result["_RS_60"] + 0.5 * result["_VOL_R"]
    result["score"] += result["phase"].map({"accel_up": 3, "decel_down": 2, "decel_up": 0.5, "accel_down": -2}).fillna(0)
    result = result.sort_values("score", ascending=False).head(10)
    result["rank"] = range(1, len(result) + 1)
    return [_json_value(row) for row in result.drop(columns=["_MOM_21", "_RS_60", "_VOL_R"]).to_dict("records")]


def _rsi(close: pd.Series) -> float | None:
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    value = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    return _round(value.iloc[-1] - 50 if pd.notna(value.iloc[-1]) else None)


def _load_stocks(industries: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
    names = [str(item["industry"]) for item in industries]
    if not names:
        return []
    placeholders = ",".join(["%s"] * len(names))
    field = "sector_1" if params["industry_level"] == 1 else "sector_2"
    status = execute_query(f"SELECT stock_code, stock_name, {field} AS industry FROM trade_stock_status WHERE {field} IN ({placeholders})", names)
    if not status:
        return []
    code_to_meta = {row["stock_code"]: row for row in status}
    codes = list(code_to_meta)
    latest = execute_query("SELECT MAX(trade_date) AS trade_date FROM trade_stock_daily WHERE stock_code IN (" + ",".join(["%s"] * len(codes)) + ")", codes)
    latest_date = latest[0].get("trade_date") if latest else None
    start = str(pd.to_datetime(latest_date or date.today()) - timedelta(days=max(params["lookback"] * 2, 220)))[:10]
    daily = execute_query("SELECT stock_code, trade_date, close_price, volume, amount FROM trade_stock_daily WHERE stock_code IN (" + ",".join(["%s"] * len(codes)) + ") AND adjustflag=2 AND trade_date >= %s ORDER BY stock_code, trade_date ASC", [*codes, start])
    if not daily:
        return []
    frame = pd.DataFrame(daily)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    for col in ["close_price", "volume", "amount"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    raw: list[dict[str, Any]] = []
    for code, group in frame.groupby("stock_code"):
        close = group.sort_values("trade_date")["close_price"].dropna()
        if len(close) < 130:
            continue
        returns = close.pct_change().dropna()
        ma20 = close.rolling(20).mean().iloc[-1]
        raw.append({"code": code, "stock_name": code_to_meta[code].get("stock_name"), "industry": code_to_meta[code].get("industry"), "alpha": None, "raw_factors": {"MOM_1M": _round(close.iloc[-1] / close.iloc[-22] - 1), "MOM_3M": _round(close.iloc[-1] / close.iloc[-64] - 1), "VOL_20": _round(-returns.tail(20).std() * np.sqrt(250)), "RSI_14": _rsi(close), "BIAS_20": _round(-(close.iloc[-1] - ma20) / ma20 if ma20 else None)}, "data_as_of": str(group["trade_date"].max().date())})
    if not raw:
        return []
    result = pd.DataFrame([{**item["raw_factors"], "code": item["code"]} for item in raw]).set_index("code")
    for col in ["MOM_1M", "MOM_3M", "VOL_20", "RSI_14", "BIAS_20"]:
        result[col] = _zscore(result[col].astype(float))
    result["alpha"] = result["MOM_1M"] * 0.25 + result["MOM_3M"] * 0.25 + result["VOL_20"] * 0.15 + result["RSI_14"] * 0.2 + result["BIAS_20"] * 0.15
    by_code = {item["code"]: item for item in raw}
    for code, row in result.sort_values("alpha", ascending=False).head(params["top_stocks"]).iterrows():
        by_code[code]["alpha"] = _round(row["alpha"])
        by_code[code]["factor_contributions"] = {key: _round(float(row[key]) * weight) for key, weight in {"MOM_1M": .25, "MOM_3M": .25, "VOL_20": .15, "RSI_14": .2, "BIAS_20": .15}.items()}
        by_code[code]["signal"] = "重点观察" if row["alpha"] >= 0 else "观察"
        by_code[code]["intraday_advice"] = "关注开盘 30 分钟方向，等待板块与个股同步确认"
    return [_json_value(by_code[code]) for code in result.sort_values("alpha", ascending=False).head(params["top_stocks"]).index]


def _build_report(state: dict[str, Any]) -> tuple[str, str, str]:
    now = datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    industries = state.get("industry_rank", [])
    stocks = state.get("picked_stocks", [])
    top = industries[0]["industry"] if industries else "暂无有效板块"
    summary = f"今日强势方向：{top}。共识候选 {len(stocks)} 只，建议结合开盘 30 分钟方向确认；板块强度不代表板块内所有个股同步上涨。"
    state["summary"] = summary
    lines = [f"# 晨会分析（{state.get('data_as_of') or '-'}）", "", f"> 生成时间：{now.isoformat(timespec='seconds')}", "", "## 核心结论", summary, "", "## Top 强势板块", "", "| 排名 | 板块 | 综合分 | 拐点 | 21日动量 | 60日相对强度 | 20日ROC |", "|---:|---|---:|---|---:|---:|---:|"]
    lines += [f"| {x.get('rank','-')} | {x.get('industry','-')} | {_round(x.get('score'),3) or '-'} | {x.get('phase_desc','-')} | {_round(x.get('MOM_21'),4) or '-'} | {_round(x.get('RS_60'),4) or '-'} | {_round(x.get('ROC_20'),2) or '-'}% |" for x in industries]
    lines += ["", "## Top 选中标的", "", "| 代码 | 名称 | 板块 | Alpha | 1M动量 | 3M动量 | 20D波动率 | RSI因子 |", "|---|---|---|---:|---:|---:|---:|---:|"]
    lines += [f"| {x.get('code','-')} | {x.get('stock_name','-')} | {x.get('industry','-')} | {x.get('alpha','-')} | {x['raw_factors'].get('MOM_1M','-')} | {x['raw_factors'].get('MOM_3M','-')} | {x['raw_factors'].get('VOL_20','-')} | {x['raw_factors'].get('RSI_14','-')} |" for x in stocks]
    lines += ["", "## 盘中应对", "", "- 每只候选标的关注开盘 30 分钟方向。", "- 板块强、个股中期动量为负时，视为因子分化风险，不追高。"]
    markdown = "\n".join(lines)
    html_body = "<article class='morning-report'>" + "".join(f"<p>{html.escape(line)}</p>" for line in lines if line and not line.startswith("|") and not line.startswith("#")) + "</article>"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md_path, html_path = REPORT_DIR / f"morning_brief_{stamp}.md", REPORT_DIR / f"morning_brief_{stamp}.html"
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(f"<!doctype html><html><meta charset='utf-8'><title>晨会分析</title><body>{html_body}</body></html>", encoding="utf-8")
    return markdown, str(md_path), str(html_path)


def _save_cache(state: dict[str, Any]) -> dict[str, Any]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _json_value({**state, "saved_at": datetime.now().isoformat(timespec="seconds")})
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (CACHE_DIR / f"morning_{stamp}.json").write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    LATEST_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return cache


def load_latest() -> dict[str, Any]:
    if not LATEST_CACHE.exists():
        return {}
    try:
        return json.loads(LATEST_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def list_history(limit: int = 20) -> list[dict[str, Any]]:
    files = sorted(CACHE_DIR.glob("morning_*.json"), reverse=True)[:limit]
    result = []
    for path in files:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            result.append({"saved_at": item.get("saved_at"), "data_as_of": item.get("data_as_of"), "status": item.get("workflow_status"), "path": str(path), "industry_count": len(item.get("industry_rank", [])), "stock_count": len(item.get("picked_stocks", []))})
        except (OSError, json.JSONDecodeError):
            continue
    return result


def run(params: dict[str, Any], emit: Callable[[str, dict[str, Any]], None] | None = None) -> dict[str, Any]:
    if not RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("已有晨会任务正在运行，请稍后重试")
    try:
        config = _params(params)
        state: dict[str, Any] = {"run_id": str(uuid.uuid4()), "trigger_time": datetime.now().isoformat(timespec="seconds"), "params": config, "workflow_status": "running", "messages": []}

        # 在晨会分析开始前，先同步K线数据到最新
        logger.info("晨会分析前检查并同步K线数据...")
        if emit:
            emit("progress", {"current_node": "sync_kline", "node_index": 0, "total_nodes": 5, "message": "正在检查K线数据..."})
        _ensure_kline_data_synced(emit)
        state["messages"].append("K线数据检查完成")
        if emit:
            emit("node_done", {"node": "sync_kline", "node_label": "K线数据同步", "state": {"messages": state["messages"]}})

        def node(name: str, fn: Callable[[], None]) -> None:
            if emit:
                emit("progress", {"current_node": name, "node_index": NODE_ORDER.index(name) + 2, "total_nodes": 5, "message": f"正在执行：{NODE_LABELS[name]}"})
            fn()
            state["messages"].append(f"{NODE_LABELS[name]}完成")
            if emit:
                emit("node_done", {"node": name, "node_label": NODE_LABELS[name], "state": {"industry_rank": state.get("industry_rank", []), "picked_stocks": state.get("picked_stocks", []), "messages": state["messages"]}})
        node("industry", lambda: state.update({"industry_rank": _load_industries(config["industry_level"], config["lookback"])}))
        state["data_as_of"] = (state.get("industry_rank") or [{}])[0].get("data_as_of")
        node("stock_picker", lambda: state.update({"picked_stocks": _load_stocks(state.get("industry_rank", [])[:config["top_industries"]], config)}))
        node("report", lambda: state.update(dict(zip(["report_markdown", "report_markdown_path", "report_html_path"], _build_report(state)))))
        def push() -> None:
            if config["enable_push"]:
                logger.info("morning_brief_push run_id=%s stocks=%s", state["run_id"], len(state.get("picked_stocks", [])))
                state["push_status"] = {"console": "success", "external": "not_configured"}
            else:
                state["push_status"] = {"console": "disabled"}
        node("push", push)
        state["workflow_status"] = "completed"
        cache = _save_cache(state)
        if emit:
            emit("done", cache)
        return cache
    except Exception:
        logger.exception("morning_brief_run_failed")
        raise
    finally:
        RUN_LOCK.release()
