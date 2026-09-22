"""缠论基础结构：分型、笔、线段和中枢。"""
from __future__ import annotations

import pandas as pd


def detect_fractals(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"high", "low"}
    if not required.issubset(frame.columns):
        raise ValueError("缠论行情缺少 high/low 字段")
    high, low = frame["high"], frame["low"]
    top = (high > high.shift(1)) & (high >= high.shift(-1))
    bottom = (low < low.shift(1)) & (low <= low.shift(-1))
    result = pd.DataFrame(index=frame.index)
    result["top_fractal"] = top.fillna(False)
    result["bottom_fractal"] = bottom.fillna(False)
    return result


def build_strokes(frame: pd.DataFrame, fractals: pd.DataFrame | None = None) -> pd.DataFrame:
    fractals = fractals if fractals is not None else detect_fractals(frame)
    points = []
    for date, row in fractals.iterrows():
        if row.bottom_fractal:
            points.append((date, float(frame.at[date, "low"]), "bottom"))
        elif row.top_fractal:
            points.append((date, float(frame.at[date, "high"]), "top"))
    strokes = []
    for point in points:
        if not strokes:
            strokes.append(point)
            continue
        previous = strokes[-1]
        if point[2] == previous[2]:
            better = point[1] < previous[1] if point[2] == "bottom" else point[1] > previous[1]
            if better:
                strokes[-1] = point
            continue
        if (point[0] - previous[0]).days >= 2:
            strokes.append(point)
    result = pd.DataFrame(strokes, columns=["date", "price", "kind"])
    return result.set_index("date") if not result.empty else pd.DataFrame(columns=["price", "kind"])


def build_centers(strokes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if strokes is None or len(strokes) < 3:
        return pd.DataFrame(columns=["start", "end", "lower", "upper"])
    values = list(strokes.reset_index().itertuples(index=False))
    for first, second, third in zip(values, values[1:], values[2:]):
        prices = [first.price, second.price, third.price]
        lower, upper = max(min(prices[0], prices[1]), min(prices[1], prices[2])), min(max(prices[0], prices[1]), max(prices[1], prices[2]))
        if lower < upper:
            rows.append({"start": first.date, "end": third.date, "lower": lower, "upper": upper})
    return pd.DataFrame(rows)
