"""订单完成回调驱动的交易配对与退出原因记录。"""
from collections import deque
from dataclasses import dataclass, field
from typing import Any
import pandas as pd

COMPLETED = {"completed", "filled", "partial"}
REJECTED = {"cancelled", "canceled", "rejected", "margin", "expired"}
EXIT_REASONS = {"first_sell", "second_sell", "third_sell", "atr_stop", "breakeven_stop", "profit_lock_stop", "initial_zg_stop", "fallback_stop", "final_close", "manual_or_other"}

@dataclass
class _Lot:
    date: pd.Timestamp
    price: float
    quantity: float
    fee: float = 0.0

@dataclass
class OrderTradeTracker:
    stock_code: str = ""
    atr_exit_mult: float | None = None
    pending_exit_reason: str | None = None
    pending_trigger_info: list[str] = field(default_factory=list)
    _lots: deque = field(default_factory=deque)
    trades: list[dict[str, Any]] = field(default_factory=list)
    ignored_orders: list[dict[str, Any]] = field(default_factory=list)
    _pending_order_id: Any = None
    _pending_order_remaining: float = 0.0

    def set_exit_reason(self, reason: str, triggered_rules: list[str] | None = None, order_id: Any = None, quantity: float | None = None) -> None:
        self.pending_exit_reason = reason if reason in EXIT_REASONS else "manual_or_other"
        self.pending_trigger_info = list(triggered_rules or [self.pending_exit_reason])
        self._pending_order_id = order_id
        self._pending_order_remaining = float(quantity or 0)

    def notify_order(self, order: dict[str, Any]) -> None:
        status = str(order.get("status", "completed")).lower()
        executed = float(order.get("executed_quantity", order.get("quantity", 0)) or 0)
        if status not in COMPLETED or executed <= 0:
            self.ignored_orders.append({**order, "ignored": True})
            return
        side = str(order.get("side", order.get("type", ""))).upper()
        order_id = order.get("order_id", order.get("id"))
        date = pd.Timestamp(order.get("executed_date", order.get("date")))
        price = float(order.get("executed_price", order.get("price")))
        fee = float(order.get("commission", order.get("fee", 0)) or 0)
        if side in {"BUY", "B"}:
            self._lots.append(_Lot(date, price, executed, fee))
            return
        if side not in {"SELL", "S"}:
            self.ignored_orders.append({**order, "ignored": True, "reason": "unknown_side"})
            return
        remaining = executed
        while remaining > 0 and self._lots:
            lot = self._lots[0]
            qty = min(remaining, lot.quantity)
            gross = (price - lot.price) * qty
            total_fee = lot.fee * qty / lot.quantity + fee * qty / executed
            self.trades.append({
                "stock_code": self.stock_code, "atr_exit_mult": self.atr_exit_mult,
                "entry_date": lot.date, "entry_price": lot.price, "entry_quantity": qty,
                "exit_date": date, "exit_price": price, "exit_quantity": qty,
                "gross_profit": gross, "fee": total_fee, "net_profit": gross - total_fee,
                "return_pct": (price / lot.price - 1) if lot.price else 0.0,
                "net_return_pct": ((gross - total_fee) / (lot.price * qty)) if lot.price and qty else 0.0,
                "holding_trading_days": max(0, int((date.normalize() - lot.date.normalize()).days)),
                "holding_calendar_days": max(0, int((date - lot.date).days)),
                "holding_days": max(0, int((date - lot.date).days)),
                "exit_reason": self.pending_exit_reason or "manual_or_other",
                "exit_triggered_rules": ",".join(self.pending_trigger_info),
                "order_id": order_id,
                "execution_status": "filled",
                "order_status": status,
            })
            lot.quantity -= qty
            remaining -= qty
            if lot.quantity <= 1e-12:
                self._lots.popleft()
        if self._pending_order_id is None or self._pending_order_id == order_id:
            if self._pending_order_remaining:
                self._pending_order_remaining = max(0.0, self._pending_order_remaining - executed)
            if not self._pending_order_remaining:
                self.pending_exit_reason = None
                self.pending_trigger_info = []
                self._pending_order_id = None

        if remaining > 0:
            self.ignored_orders.append({**order, "ignored": True, "reason": "unmatched_sell", "unmatched_quantity": remaining})

    def finalize(self) -> list[dict[str, Any]]:
        return [{"stock_code": self.stock_code, "atr_exit_mult": self.atr_exit_mult,
                 "entry_date": lot.date, "entry_price": lot.price, "entry_quantity": lot.quantity,
                 "exit_date": None, "exit_price": None, "exit_quantity": 0,
                 "gross_profit": None, "fee": lot.fee, "net_profit": None, "return_pct": None,
                 "holding_trading_days": None, "holding_calendar_days": None, "holding_days": None,
                 "status": "open_at_end", "exit_reason": None, "exit_triggered_rules": "",
                 "order_id": None, "execution_status": "open"} for lot in self._lots]

def pair_completed_orders(orders: list[dict[str, Any]], stock_code: str = "", atr_exit_mult: float | None = None) -> tuple[list[dict], list[dict]]:
    tracker = OrderTradeTracker(stock_code, atr_exit_mult)
    for order in orders:
        tracker.notify_order(order)
    return tracker.trades, tracker.finalize()
