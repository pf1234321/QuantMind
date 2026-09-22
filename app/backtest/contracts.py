from dataclasses import dataclass, field
from typing import Any, Callable
import pandas as pd


@dataclass(frozen=True)
class StrategyAdapter:
    run: Callable[[pd.DataFrame, float, Any], "BacktestResult"]
    source_description: str
    run_mode: str = "full_history"
    lookahead_risk: bool = True


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
