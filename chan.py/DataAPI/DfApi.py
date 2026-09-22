# -*- coding: utf-8 -*-
from Common.CEnum import KL_TYPE, DATA_FIELD, AUTYPE
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.CommonStockAPI import CCommonStockApi

_DF_CACHE = {}


class DfApi(CCommonStockApi):
    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super().__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self):
        df = _DF_CACHE.get(self.code)
        if df is None:
            return
        for i in range(len(df)):
            row = df.iloc[i]
            dt = df.index[i]
            kl_dict = {
                DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, 0, 0),
                DATA_FIELD.FIELD_OPEN: float(row["open"]),
                DATA_FIELD.FIELD_HIGH: float(row["high"]),
                DATA_FIELD.FIELD_LOW: float(row["low"]),
                DATA_FIELD.FIELD_CLOSE: float(row["close"]),
                DATA_FIELD.FIELD_VOLUME: float(row["volume"]),
            }
            yield CKLine_Unit(kl_dict)

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass
