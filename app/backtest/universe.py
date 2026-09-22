"""按历史时点构建可交易股票池；缺少基础资料的字段不会被伪造。"""
from dataclasses import dataclass, asdict
import pandas as pd

@dataclass(frozen=True)
class UniverseConfig:
    min_listing_days: int = 250
    min_history_coverage: float = 0.95
    market_filter: str | None = None
    industry_filter: tuple[str, ...] | None = None
    exclude_suspended: bool = True
    exclude_limit_locked: bool = True
    exclude_risk_warning: bool = True
    max_missing_ratio: float = 0.05
    min_price: float = 3.0
    min_avg_amount: float = 0.0
    min_median_amount: float = 0.0
    max_low_amount_ratio: float = 1.0
    low_amount_threshold: float = 0.0
    max_atr_ratio: float | None = None
    max_stock_weight: float = 0.10
    max_industry_weight: float = 0.25
    def as_dict(self): return asdict(self)

def filter_stock(stock_code: str, frame: pd.DataFrame, as_of_date=None, config: UniverseConfig | None = None, listing_date=None, status=None, industry=None) -> dict:
    config = config or UniverseConfig()
    as_of = pd.Timestamp(as_of_date) if as_of_date is not None else frame.index.max()
    data = frame.loc[frame.index <= as_of].sort_index()
    reasons = []
    required = {"open", "high", "low", "close"}
    missing = sorted(required.difference(data.columns))
    if missing:
        reasons.append("missing_columns:" + ",".join(missing))
        return {"stock_code": stock_code, "as_of_date": str(as_of.date()), "eligible": False, "filter_reason": ",".join(reasons), "industry": industry, "listing_date": listing_date, "config": config.as_dict()}
    if data.empty: reasons.append("empty_data")
    if len(data) < config.min_listing_days: reasons.append("insufficient_history")
    if "close" in data and not data.empty and float(data.close.iloc[-1]) < config.min_price: reasons.append("price_too_low")
    amount = pd.to_numeric(data.get("amount", pd.Series(index=data.index, dtype=float)), errors="coerce")
    valid = amount.notna().sum() / len(data) if len(data) else 0
    if valid < config.min_history_coverage: reasons.append("low_data_coverage")
    if not amount.empty:
        if amount.mean() < config.min_avg_amount: reasons.append("low_average_amount")
        if amount.median() < config.min_median_amount: reasons.append("low_median_amount")
        if config.low_amount_threshold and (amount < config.low_amount_threshold).mean() > config.max_low_amount_ratio: reasons.append("low_liquidity_days")
    if listing_date is not None and (as_of - pd.Timestamp(listing_date)).days < config.min_listing_days: reasons.append("listing_too_recent")
    if status == "suspended" and config.exclude_suspended: reasons.append(status)
    if status in {"risk_warning", "delisting"} and config.exclude_risk_warning: reasons.append(status)
    if status == "limit_locked" and config.exclude_limit_locked: reasons.append(status)
    if config.industry_filter and industry not in config.industry_filter: reasons.append("industry_filtered")
    atr_ratio = None
    if len(data) >= 15:
        tr = pd.concat([data.high-data.low, (data.high-data.close.shift()).abs(), (data.low-data.close.shift()).abs()], axis=1).max(axis=1)
        atr_ratio = float(tr.rolling(14).mean().iloc[-1] / data.close.iloc[-1])
        if config.max_atr_ratio is not None and atr_ratio > config.max_atr_ratio: reasons.append("volatility_too_high")
    return {"stock_code": stock_code, "as_of_date": str(as_of.date()), "eligible": not reasons, "filter_reason": ",".join(reasons) or "eligible", "industry": industry, "listing_date": listing_date, "data_start": str(data.index.min().date()) if not data.empty else None, "data_end": str(data.index.max().date()) if not data.empty else None, "data_coverage": valid, "atr_ratio": atr_ratio, "config": config.as_dict()}

def build_universe(frames: dict[str, pd.DataFrame], as_of_date=None, config: UniverseConfig | None = None, metadata: dict | None = None) -> pd.DataFrame:
    metadata = metadata or {}
    return pd.DataFrame([filter_stock(code, frame, as_of_date, config, **metadata.get(code, {})) for code, frame in sorted(frames.items())])
