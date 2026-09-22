from datetime import date
from decimal import Decimal
from typing import Iterable

DEFAULT_MULTIPLIERS = (1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0, 4.5)


def validate_multipliers(multipliers: Iterable[float] | None = None, range_start: float | None = None, range_end: float | None = None, step: float | None = None) -> tuple[float, ...]:
    if multipliers is not None:
        if any(v is not None for v in (range_start, range_end, step)):
            raise ValueError("multipliers 与 range_start/range_end/step 不能同时使用")
        values = tuple(float(value) for value in multipliers)
        if not values or any(value <= 0 for value in values):
            raise ValueError("multipliers 必须包含至少一个正数")
        return tuple(dict.fromkeys(values))
    if all(v is None for v in (range_start, range_end, step)):
        return DEFAULT_MULTIPLIERS
    if None in (range_start, range_end, step) or step <= 0 or range_start > range_end:
        raise ValueError("参数范围必须提供起止值，且 step 必须为正、start 不得大于 end")
    values = []
    current = Decimal(str(range_start))
    end = Decimal(str(range_end))
    increment = Decimal(str(step))
    while current <= end:
        values.append(float(current))
        current += increment
    if not values:
        raise ValueError("参数范围没有生成候选值")
    return tuple(dict.fromkeys(values))


def actual_range(frame, start: str, end: str) -> tuple[str, str]:
    if frame is None or len(frame) == 0:
        raise ValueError("行情数据为空")
    requested_start, requested_end = date.fromisoformat(start), date.fromisoformat(end)
    if requested_start > requested_end:
        raise ValueError("start_date 不得晚于 end_date")
    dates = frame.index
    first, last = dates.min().date(), dates.max().date()
    left, right = max(first, requested_start), min(last, requested_end)
    if left > right:
        raise ValueError("请求区间与实际行情没有交集")
    return left.isoformat(), right.isoformat()
