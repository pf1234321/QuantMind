from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 100000.0
    position_pct: float = 0.95
    commission: float = 0.001
    slippage: float = 0.0
    atr_period: int = 14
    breakeven_pct: float = 0.05
    lock_profit_pct: float = 0.10
    lock_amount_pct: float = 0.05
    min_trades: int = 3
    max_acceptable_drawdown: float | None = None

    def __post_init__(self) -> None:
        if self.initial_cash <= 0 or not 0 < self.position_pct <= 1:
            raise ValueError("initial_cash 必须为正，position_pct 必须在(0,1]内")
        if self.atr_period <= 0 or self.commission < 0 or self.slippage < 0:
            raise ValueError("atr_period 必须为正，手续费和滑点不能为负")
        if self.min_trades < 0:
            raise ValueError("min_trades 不能为负")
