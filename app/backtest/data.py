import pandas as pd


def normalize_daily_bars(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        raise ValueError("行情数据为空")
    frame = pd.DataFrame(rows).rename(columns={
        "trade_date": "date", "open_price": "open", "high_price": "high",
        "low_price": "low", "close_price": "close", "amount": "amount",
        "turnover_rate": "turnover",
    })
    required = ["date", "open", "high", "low", "close"]
    missing = [name for name in required if name not in frame]
    if missing:
        raise ValueError(f"行情缺少字段: {', '.join(missing)}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    for name in ["open", "high", "low", "close", "volume", "amount", "turnover"]:
        if name in frame:
            frame[name] = pd.to_numeric(frame[name], errors="coerce")
    frame = frame.dropna(subset=required).sort_values("date")
    if frame.empty:
        raise ValueError("行情数据为空")
    if frame["date"].duplicated().any():
        raise ValueError("行情包含重复交易日")
    frame = frame.set_index("date")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("行情 OHLC 必须为正数")
    return frame.copy()


def load_daily_bars(stock_code: str, start_date: str, end_date: str, query_fn) -> pd.DataFrame:
    code = stock_code.split(".", 1)[0]
    rows = query_fn(
        "SELECT trade_date, open_price, high_price, low_price, close_price, volume, amount, turnover_rate "
        "FROM trade_stock_daily WHERE stock_code=%s AND trade_date BETWEEN %s AND %s ORDER BY trade_date",
        (code, start_date, end_date),
    )
    return normalize_daily_bars(rows)
