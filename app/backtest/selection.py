import pandas as pd


def rank_results(frame: pd.DataFrame) -> dict[str, list[float]]:
    return {
        "total_return": frame.sort_values("total_return", ascending=False).atr_exit_mult.tolist(),
        "max_drawdown": frame.sort_values("max_drawdown").atr_exit_mult.tolist(),
        "calmar_ratio": frame.sort_values("calmar_ratio", ascending=False, na_position="last").atr_exit_mult.tolist(),
        "sharpe_ratio": frame.sort_values("sharpe_ratio", ascending=False, na_position="last").atr_exit_mult.tolist(),
    }


def confidence_level(trade_count: int) -> str:
    if trade_count < 3:
        return "very_low"
    if trade_count < 10:
        return "low"
    if trade_count < 30:
        return "medium"
    return "higher"


def add_confidence(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["confidence"] = result["trade_count"].fillna(0).astype(int).map(confidence_level)
    return result


def select_stable(frame: pd.DataFrame, min_trades: int, max_drawdown: float | None = None) -> dict:
    frame = add_confidence(frame)
    eligible = frame[(~frame.low_confidence) & (frame.trade_count >= min_trades)].copy()
    if max_drawdown is not None:
        eligible = eligible[eligible.max_drawdown >= -abs(max_drawdown)]
    if eligible.empty:
        return {"interval": None, "recommended": None, "possible_overfit": [], "reason": "没有满足交易数和回撤约束的参数"}
    core = ["annualized_return", "calmar_ratio", "sharpe_ratio"]
    for col in core:
        eligible[f"rank_{col}"] = eligible[col].rank(pct=True)
    eligible["score"] = eligible[[f"rank_{c}" for c in core]].mean(axis=1)
    eligible = eligible.sort_values("atr_exit_mult").reset_index(drop=True)
    best_index = int(eligible.score.idxmax())
    score_floor = float(eligible.score.median())
    stable = eligible[eligible.score >= score_floor]
    interval = [float(stable.atr_exit_mult.min()), float(stable.atr_exit_mult.max())]
    recommended = float(eligible.loc[best_index, "atr_exit_mult"])
    if interval[0] != interval[1]:
        midpoint = (interval[0] + interval[1]) / 2
        recommended = float(eligible.iloc[(eligible.atr_exit_mult - midpoint).abs().idxmin()].atr_exit_mult)
    ordered = frame.sort_values("atr_exit_mult").reset_index(drop=True)
    overfit = []
    for i in range(1, len(ordered) - 1):
        row = ordered.iloc[i]
        neighbors = ordered.iloc[[i - 1, i + 1]]
        neighbor_return = float(neighbors.total_return.mean())
        if row.total_return > neighbors.total_return.max() and row.total_return - neighbor_return > max(0.05, abs(neighbor_return) * 0.5):
            overfit.append(float(row.atr_exit_mult))
    return {"interval": interval, "recommended": recommended, "possible_overfit": overfit, "reason": None}
