"""Adapter for Vespa314/chan.py using the project's DataFrame K-line data."""
from __future__ import annotations

from datetime import date
import importlib
import os
import sys
from typing import Any

import pandas as pd


def _load_chanpy() -> None:
    root = os.getenv("CHANPY_PATH")
    if root and root not in sys.path:
        sys.path.insert(0, root)


def chanpy_available() -> bool:
    _load_chanpy()
    try:
        importlib.import_module("Chan")
        return True
    except ImportError:
        return False


class DataFrameStockAPI:
    """chan.py data source backed by one in-memory daily DataFrame."""

    frame: pd.DataFrame = pd.DataFrame()

    def __init__(self, code, k_type, begin_date, end_date, autype):
        self.code = code
        self.begin_date = begin_date
        self.end_date = end_date

    @classmethod
    def set_frame(cls, frame: pd.DataFrame) -> None:
        cls.frame = frame.sort_index()

    def get_kl_data(self):
        from Common.CTime import CTime  # type: ignore[import-not-found]
        from Common.CEnum import DATA_FIELD  # type: ignore[import-not-found]
        from KLine.KLine_Unit import CKLine_Unit  # type: ignore[import-not-found]

        frame = self.frame
        if self.begin_date is not None:
            frame = frame.loc[frame.index >= pd.Timestamp(self.begin_date)]
        if self.end_date is not None:
            frame = frame.loc[frame.index <= pd.Timestamp(self.end_date)]
        for timestamp, row in frame.iterrows():
            value = timestamp.to_pydatetime()
            yield CKLine_Unit({
                DATA_FIELD.FIELD_TIME: CTime(value.year, value.month, value.day, 0, 0),
                DATA_FIELD.FIELD_OPEN: float(row.open),
                DATA_FIELD.FIELD_HIGH: float(row.high),
                DATA_FIELD.FIELD_LOW: float(row.low),
                DATA_FIELD.FIELD_CLOSE: float(row.close),
            })

    def SetBasciInfo(self):
        pass

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass


def detect_chanpy_signals(
    frame: pd.DataFrame,
    stock_code: str = "",
    end_date: date | str | None = None,
) -> list[dict[str, Any]]:
    """Calculate confirmed chan.py BSPs without using data after end_date."""
    if frame.empty or not {"open", "high", "low", "close"}.issubset(frame.columns):
        return []
    if not chanpy_available():
        raise RuntimeError("chan.py is not installed; install it from Vespa314/chan.py")

    _load_chanpy()
    importlib.import_module("DataAPI")
    sys.modules["DataAPI.quantmind_adapter"] = sys.modules[__name__]
    from Chan import CChan  # type: ignore[import-not-found]
    from ChanConfig import CChanConfig  # type: ignore[import-not-found]
    from Common.CEnum import AUTYPE, KL_TYPE  # type: ignore[import-not-found]

    data = frame.sort_index()
    if end_date is not None:
        data = data.loc[data.index <= pd.Timestamp(end_date)]
    if len(data) < 20:
        return []

    DataFrameStockAPI.set_frame(data)
    config = CChanConfig({
        "trigger_step": False,
        "bi_strict": True,
        "bi_fx_check": "strict",
        "print_warning": False,
        "print_err_time": False,
    })
    chan = CChan(
        stock_code or "FRAME",
        end_time=str(pd.Timestamp(data.index[-1]).date()),
        data_src="custom:quantmind_adapter.DataFrameStockAPI",
        lv_list=[KL_TYPE.K_DAY],
        config=config,
        autype=AUTYPE.NONE,
    )
    rows: list[dict[str, Any]] = []
    for point in chan.get_bsp(0):
        types = [item.value for item in point.type]
        main_type = types[0][0]
        signal_type = ("first_buy" if main_type == "1" else "second_buy" if main_type == "2" else "third_buy") if point.is_buy else ("first_sell" if main_type == "1" else "second_sell" if main_type == "2" else "third_sell")
        klu = point.klu
        signal_date = f"{klu.time.year:04d}-{klu.time.month:02d}-{klu.time.day:02d}"
        rows.append({
            "stock_code": stock_code,
            "signal_type": signal_type,
            "signal_date": signal_date,
            "confirmed_date": signal_date,
            "signal_status": "confirmed",
            "signal_level": "daily",
            "signal_price": float(klu.close),
            "signal_strength": "high" if main_type == "3" else "medium",
            "confidence": "high",
            "lookahead_risk": False,
            "engine": "chan.py",
            "chan_type": ",".join(types),
            "pivot_date": signal_date,
        })
    return rows
