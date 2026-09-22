from app.services.diagnosis_risk_reward import calculate_risk_reward, calculate_stop_loss, calculate_volatility


def _series(days: int = 80, start: float = 10.0) -> list[dict]:
    rows = []
    close = start
    for index in range(days):
        close = round(start + index * 0.05, 4)
        high = round(close + 0.4, 4)
        low = round(close - 0.3, 4)
        rows.append({"high": high, "low": low, "close": close, "high_price": high, "low_price": low, "close_price": close})
    return rows


def test_volatility_outputs_hv20_hv60_and_atr14():
    result = calculate_volatility({"series": _series()})

    assert result["hv20"] is not None
    assert result["hv60"] is not None
    assert result["atr14"] is not None
    assert result["hv20"] > 0
    assert result["atr14"] > 0


def test_atr_stop_uses_hv_mapped_multiple():
    close = 10.0
    stop = calculate_stop_loss(
        close,
        support=9.2,
        volatility={"hv20": 0.25, "atr14": 0.4},
        config={"stop_mode": "atr"},
        series=_series(),
    )

    assert stop["type"] == "atr"
    assert stop["price"] == 9.2
    assert stop["atr_multiple"] == 2.0
    assert "入场价 - 2.0×ATR14" in stop["trigger"]
    assert stop["fallback_used"] is False


def test_trailing_atr_stop_uses_recent_high():
    series = _series()
    close = series[-1]["close"]
    stop = calculate_stop_loss(
        close,
        support=close - 1.5,
        volatility={"hv20": 0.2, "atr14": 0.3},
        config={"stop_mode": "trailing_atr", "atr_multiple": 1.5, "trailing_lookback": 20},
        series=series,
    )

    recent_high = max(row["high"] for row in series[-20:])
    expected = round(recent_high - 1.5 * 0.3, 4)
    assert stop["type"] == "trailing_atr"
    assert stop["price"] == expected
    assert "近20日高点" in stop["trigger"]


def test_support_mode_falls_back_to_budget_when_needed():
    stop = calculate_stop_loss(
        10.0,
        support=10.5,
        volatility={"hv20": 0.2, "atr14": None},
        config={"stop_mode": "support", "risk_budget": 0.08},
        series=[],
    )

    assert stop["type"] == "budget"
    assert stop["price"] == 9.2
    assert stop["fallback_used"] is True
    assert "风险预算" in stop["trigger"]


def test_risk_reward_uses_volatility_in_stop_and_holding_period():
    series = _series()
    close = series[-1]["close"]
    result = calculate_risk_reward(
        {"close": close, "series": series, "data_as_of": "2026-09-01", "data_source": "test"},
        {"support": close - 1.2, "resistance": close + 2.0},
        {"stop_mode": "atr", "atr_multiple": 2.0, "min_holding_days": 5, "max_holding_days": 60},
    )

    assert result["status"] == "completed"
    assert result["rule_version"] == "risk-reward-v2"
    assert result["stop_loss"]["type"] == "atr"
    assert result["stop_loss"]["price"] is not None
    assert result["stop_loss"]["trigger"]
    assert result["volatility"]["hv20"] is not None
    assert result["volatility"]["hv60"] is not None
    assert result["volatility"]["atr14"] is not None
    assert 5 <= result["holding_period"]["days"] <= 60
    assert result["quality_checks"]["atr14_available"] is True
