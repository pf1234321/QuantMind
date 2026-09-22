"""机会看板与缠论信号详情接口。"""
from __future__ import annotations

from datetime import date
import math
import re


from fastapi import APIRouter, HTTPException, Query

from app.backtest.data import load_daily_bars
from app.backtest.daily import run_daily_scan
from app.database import execute_query
from app.signals import SignalStore

router = APIRouter(prefix="/opportunities", tags=["机会看板"])

BUY_TYPES = {"first_buy", "second_buy", "third_buy"}
SELL_TYPES = {"first_sell", "second_sell", "third_sell"}


def _category(signal_type: str) -> str:
    return "chan-buy" if signal_type in BUY_TYPES else "chan-sell" if signal_type in SELL_TYPES else "other"


def _stock_market_data(rows: list[dict]) -> dict[tuple[str, str], dict]:
    pairs = sorted({
        (str(row.get("stock_code") or ""), str(row.get("signal_date") or ""))
        for row in rows
        if row.get("stock_code") and row.get("signal_date")
    })
    if not pairs:
        return {}
    codes = sorted({code for code, _ in pairs})
    code_placeholders = ", ".join(["%s"] * len(codes))
    status_rows = execute_query(
        f"SELECT stock_code, stock_name, sector_1, sector_2, sector_3, "
        f"total_shares, float_shares FROM trade_stock_status "
        f"WHERE stock_code IN ({code_placeholders})",
        codes,
    )
    status_by_code = {str(item["stock_code"]): item for item in status_rows}
    normalized_pairs = {
        (code, signal_date)
        for code, signal_date in pairs
    }
    alias_pairs = {
        (f"{code}.SH" if code.startswith(("5", "6", "9")) else f"{code}.SZ", signal_date)
        for code, signal_date in pairs
    }
    query_pairs = sorted(normalized_pairs | alias_pairs)
    pair_placeholders = ", ".join(["(%s, %s)"] * len(query_pairs))
    daily_rows = execute_query(
        "SELECT stock_code, trade_date, close_price, volume, amount, turnover_rate "
        "FROM trade_stock_daily WHERE (stock_code, trade_date) IN ("
        + pair_placeholders
        + ")",
        [value for pair in query_pairs for value in pair],
    )
    daily_by_pair = {}
    for item in daily_rows:
        code = str(item["stock_code"]).split(".", 1)[0]
        daily_by_pair[(code, str(item["trade_date"]))] = item
    latest_rows = execute_query(
        "SELECT d.stock_code, d.trade_date, d.close_price "
        "FROM trade_stock_daily d "
        "INNER JOIN (SELECT stock_code, MAX(trade_date) AS latest_date "
        "FROM trade_stock_daily WHERE stock_code IN (" + code_placeholders + ") "
        "OR stock_code IN (" + ", ".join(["%s"] * len(codes)) + ") "
        "GROUP BY stock_code) latest "
        "ON latest.stock_code = d.stock_code AND latest.latest_date = d.trade_date",
        codes + [f"{code}.SH" if code.startswith(("5", "6", "9")) else f"{code}.SZ" for code in codes],
    )
    latest_by_code = {}
    for item in latest_rows:
        code = str(item["stock_code"]).split(".", 1)[0]
        current = latest_by_code.get(code)
        if current is None or str(item["trade_date"]) > str(current["trade_date"]):
            latest_by_code[code] = item
    result = {}
    for code, signal_date in pairs:
        signal_market = daily_by_pair.get((code, signal_date), {})
        latest_market = latest_by_code.get(code, {})
        result[(code, signal_date)] = {
            **status_by_code.get(code, {}),
            **signal_market,
            "latest_close_price": latest_market.get("close_price"),
            "latest_close_date": latest_market.get("trade_date"),
        }
    return result


def _json_safe(value):
    """将 Pandas/NumPy 结果转换为可被严格 JSON 编码的值。"""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _normalize(row: dict, market_data: dict | None = None) -> dict:
    signal_type = str(row.get("signal_type") or "")
    action = "candidate" if signal_type in BUY_TYPES else "exit_management" if signal_type in SELL_TYPES else "observe"
    market_data = market_data or {}
    close_price = market_data.get("close_price")
    total_shares = market_data.get("total_shares")
    float_shares = market_data.get("float_shares")
    return {
        **row,
        "stock_name": market_data.get("stock_name", row.get("stock_name", "")),
        "sector_1": market_data.get("sector_1"),
        "sector_2": market_data.get("sector_2"),
        "sector_3": market_data.get("sector_3"),
        "signal_close_price": close_price,
        "signal_market_date": market_data.get("trade_date", row.get("signal_date")),
        "latest_close_price": market_data.get("latest_close_price"),
        "latest_close_date": market_data.get("latest_close_date"),
        "volume": market_data.get("volume"),
        "amount": market_data.get("amount"),
        "turnover_rate": market_data.get("turnover_rate"),
        "total_shares": total_shares,
        "float_shares": float_shares,
        "id": "-".join(str(row.get(key) or "") for key in ("stock_code", "signal_type", "signal_date")),
        "category": _category(signal_type),
        "signal_status": row.get("signal_status", "confirmed"),
        "signal_level": row.get("signal_level", "daily"),
        "action": action,
    }


@router.get("/scan", summary="查看机会扫描调用方式")
def scan_help():
    """避免直接在浏览器地址栏访问 POST 扫描接口时出现方法错误。"""
    return {
        "message": "扫描接口需要使用 POST 请求，不支持通过浏览器地址栏直接执行。",
        "method": "POST",
        "endpoint": "/api/v1/opportunities/scan",
        "usage": "请在机会看板点击‘执行真实扫描’，或在 /docs 中调用 POST 接口。",
        "query_params": {
            "stock_code": "可选，指定股票代码，例如 000001",
            "start_date": "可选，默认 2022-01-01",
            "end_date": "可选，默认最新行情日",
            "turnover_min": "可选，换手率下限，单位百分比",
            "turnover_max": "可选，换手率上限，单位百分比",
        },
    }


@router.post("/scan", summary="执行真实机会扫描")
def scan_opportunities(
    stock_code: str | None = Query(None, description="指定单只股票代码；兼容旧调用"),
    stock_codes: str | None = Query(None, description="指定多只股票代码，支持逗号、空格或换行分隔；不传则扫描全部股票"),
    start_date: str = Query("2022-01-01", description="行情起始日期"),
    end_date: str | None = Query(None, description="扫描截止日期，默认最新行情日"),
):
    """从 MySQL 日K线执行严格无前视缠论扫描并持久化新信号。"""
    requested = stock_codes or stock_code
    if requested:
        normalized = requested.replace("，", ",")
        codes = []
        for value in re.split(r"[,\s]+", normalized):
            code = value.strip().upper()
            if not code:
                continue
            code = code.split(".", 1)[0]
            if code not in codes:
                codes.append(code)
        if not codes:
            raise HTTPException(status_code=422, detail="请至少输入一个有效股票代码")
    else:
        codes = [
            row["stock_code"] for row in execute_query(
                "SELECT DISTINCT stock_code FROM trade_stock_daily ORDER BY stock_code"
            )
        ]
    if not codes:
        raise HTTPException(status_code=422, detail="没有可用于扫描的行情数据")
    frames = {}
    for code in codes:
        try:
            frames[code] = load_daily_bars(code, start_date, end_date or str(date.today()), execute_query)
        except ValueError:
            continue
    if not frames:
        raise HTTPException(status_code=422, detail="指定范围内没有可用行情数据")
    report = run_daily_scan(
        frames,
        end_date=end_date,
        mode="research",
        signal_mode="strict_no_lookahead",
        portfolio={"signal_store": SignalStore()},
    )
    return {
        "message": "机会扫描完成",
        "scan_date": report.report["scan_date"],
        "stock_count": report.report["stock_count"],
        "candidate_count": report.report["candidate_count"],
        "exit_count": report.report["exit_count"],
        "signal_mode": report.report["signal_mode"],
        "data_source": "trade_stock_daily",
        "data": _json_safe(report.candidates.where(report.candidates.notna(), None).to_dict(orient="records")),
    }


@router.get("", summary="查询机会看板")
def list_opportunities(
    category: str = Query("all", pattern="^(all|chan-buy|chan-sell)$"),
    signal_type: list[str] | None = Query(None),
    first_buy: bool | None = Query(None, description="一买信号"),
    second_buy: bool | None = Query(None, description="二买信号"),
    third_buy: bool | None = Query(None, description="三买信号"),
    first_sell: bool | None = Query(None, description="一卖信号"),
    second_sell: bool | None = Query(None, description="二卖信号"),
    third_sell: bool | None = Query(None, description="三卖信号"),
    stock_code: str | None = Query(None),
    stock_keyword: str | None = Query(None, description="股票代码或名称关键词"),
    industry: str | None = Query(None, description="行业关键词"),
    start_date: str | None = Query(None, description="信号起始日期"),
    end_date: str | None = Query(None, description="信号截止日期"),
    turnover_min: float | None = Query(None, ge=0, description="换手率下限，单位百分比"),
    turnover_max: float | None = Query(None, ge=0, description="换手率上限，单位百分比"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
):
    # 构建信号类型过滤列表
    selected_signal_types = []
    if first_buy is True:
        selected_signal_types.append("first_buy")
    if second_buy is True:
        selected_signal_types.append("second_buy")
    if third_buy is True:
        selected_signal_types.append("third_buy")
    if first_sell is True:
        selected_signal_types.append("first_sell")
    if second_sell is True:
        selected_signal_types.append("second_sell")
    if third_sell is True:
        selected_signal_types.append("third_sell")

    # 如果没有指定具体信号类型，使用传入的 signal_type 参数
    # 如果两者都没有，则不过滤信号类型
    effective_signal_type = selected_signal_types if selected_signal_types else signal_type

    raw_rows = SignalStore().list(stock_code=stock_code, signal_type=effective_signal_type)
    if category != "all":
        raw_rows = [row for row in raw_rows if _category(str(row.get("signal_type") or "")) == category]
    if start_date:
        raw_rows = [row for row in raw_rows if str(row.get("signal_date") or "") >= start_date]
    if end_date:
        raw_rows = [row for row in raw_rows if str(row.get("signal_date") or "") <= end_date]
    if stock_keyword:
        keyword = stock_keyword.strip().lower()
        raw_rows = [row for row in raw_rows if keyword in str(row.get("stock_code") or "").lower() or keyword in str(row.get("stock_name") or "").lower()]
    if turnover_min is not None and turnover_max is not None and turnover_min > turnover_max:
        raise HTTPException(status_code=422, detail="换手率下限不能大于上限")

    raw_rows.sort(key=lambda row: str(row.get("signal_date") or ""), reverse=True)
    start = (page - 1) * page_size
    total = len(raw_rows)
    needs_market_filter = bool(industry or turnover_min is not None or turnover_max is not None)
    if needs_market_filter:
        market_data = _stock_market_data(raw_rows)
        rows = [
            _normalize(
                row,
                market_data.get((str(row.get("stock_code") or ""), str(row.get("signal_date") or ""))),
            )
            for row in raw_rows
        ]
        if industry:
            keyword = industry.strip().lower()
            rows = [row for row in rows if any(keyword in str(row.get(field) or "").lower() for field in ("sector_1", "sector_2", "sector_3"))]
        if turnover_min is not None:
            rows = [row for row in rows if row.get("turnover_rate") is not None and float(row["turnover_rate"]) >= turnover_min]
        if turnover_max is not None:
            rows = [row for row in rows if row.get("turnover_rate") is not None and float(row["turnover_rate"]) <= turnover_max]
        total = len(rows)
        data_rows = rows[start:start + page_size]
    else:
        data_rows = raw_rows[start:start + page_size]

    market_data = _stock_market_data(data_rows)
    rows = [
        _normalize(
            row,
            market_data.get((str(row.get("stock_code") or ""), str(row.get("signal_date") or ""))),
        )
        for row in data_rows
    ]
    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "data": rows,
        "signal_mode": "strict_no_lookahead",
    }


@router.get("/{stock_code}/{signal_date}", summary="查询缠论信号详情")
def signal_detail(stock_code: str, signal_date: str):
    rows = SignalStore().list(stock_code=stock_code)
    matches = [row for row in rows if str(row.get("signal_date")) == signal_date]
    if not matches:
        raise HTTPException(status_code=404, detail="未找到指定日期的缠论信号")
    market_data = _stock_market_data(matches)
    stock_data = market_data.get((stock_code, signal_date), {})
    return {
        "stock_code": stock_code,
        "stock_name": stock_data.get("stock_name", ""),
        "signal_date": signal_date,
        "signals": [_normalize(row, stock_data) for row in matches],
        "signal_mode": "strict_no_lookahead",
    }
