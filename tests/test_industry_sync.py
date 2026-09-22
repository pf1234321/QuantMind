# -*- coding: utf-8 -*-
"""使用 Tushare 同步 trade_stock_status 全字段。

数据来源：
- stock_basic：股票代码、名称、上市日期、行业
- daily_basic：总股本、流通股本
- index_classify + index_member：申万一级/二级/三级行业

运行：
    TUSHARE_TOKEN=your_token python -m unittest tests.test_industry_sync -v

默认写入数据库。设置 STOCK_STATUS_SYNC_WRITE=0 只获取并检查数据，不写库。
设置 STOCK_STATUS_SYNC_SECTOR=0 可跳过行业成分同步。
"""
import os
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.database import execute_many

try:
    import tushare as ts
except ImportError:  # pragma: no cover - 未安装依赖时跳过集成测试
    ts = None


TUSHARE_API_URL = "https://tuaremax.top"


def _load_token() -> str:
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if token:
        return token
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "TUSHARE_TOKEN":
                return value.strip().strip("\"'")
    return ""


def _new_tushare_client(token: str):
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = TUSHARE_API_URL
    return pro


def _text(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    value = str(value).strip()
    return value or None


def _db_code(value) -> str | None:
    value = _text(value)
    if not value:
        return None
    code = value.split(".", 1)[0]
    return code.zfill(6) if code.isdigit() else code


def _latest_trade_date(pro) -> str:
    today = date.today().strftime("%Y%m%d")
    calendar = pro.trade_cal(exchange="", start_date=(date.today() - timedelta(days=15)).strftime("%Y%m%d"), end_date=today)
    if calendar is not None and not calendar.empty:
        calendar = calendar[calendar["is_open"].astype(str) == "1"]
        if not calendar.empty:
            return str(calendar.iloc[-1]["cal_date"])
    return today


def _fetch_shares(pro, trade_date: str) -> dict[str, tuple[float | None, float | None]]:
    frame = pro.daily_basic(trade_date=trade_date, fields="ts_code,total_share,float_share")
    if frame is None or frame.empty:
        return {}
    result = {}
    for row in frame.itertuples(index=False):
        code = _db_code(getattr(row, "ts_code", None))
        if code:
            result[code] = (_number(getattr(row, "total_share", None)), _number(getattr(row, "float_share", None)))
    return result


def _number(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value) * 10000


def _fetch_sectors(pro) -> dict[str, dict[str, str]]:
    """分别读取申万一、二、三级行业，按成分股代码建立映射。"""
    result: dict[str, dict[str, str]] = {}
    level_targets = (("L1", "sector_1"), ("L2", "sector_2"), ("L3", "sector_3"))
    for level, target in level_targets:
        classify = pro.index_classify(level=level, src="SW2021")
        if classify is None or classify.empty:
            continue
        for item in classify.to_dict("records"):
            index_code = _text(item.get("index_code"))
            industry_name = _text(item.get("industry_name") or item.get("index_name"))
            if not index_code or not industry_name:
                continue
            members = pro.index_member(index_code=index_code, is_new="Y")
            if members is None or members.empty:
                members = pro.index_member(index_code=index_code)
            if members is None or members.empty:
                continue
            for code in members.get("con_code", pd.Series(dtype=str)).dropna():
                stock_code = _db_code(code)
                if stock_code:
                    result.setdefault(stock_code, {})[target] = industry_name
    return result


def sync_trade_stock_status(pro, write: bool = True) -> dict:
    # 不限制 list_status，避免行业接口先写入的退市股票出现基础字段为空。
    stock_basic = pro.stock_basic(exchange="", list_status="", fields="ts_code,name,list_date,industry")
    if stock_basic is None or stock_basic.empty:
        raise RuntimeError("Tushare stock_basic 未返回股票数据")

    trade_date = _latest_trade_date(pro)
    shares = _fetch_shares(pro, trade_date)
    sectors = _fetch_sectors(pro) if os.getenv("STOCK_STATUS_SYNC_SECTOR", "1") != "0" else {}
    rows = []
    for item in stock_basic.to_dict("records"):
        code = _db_code(item.get("ts_code"))
        if not code:
            continue
        sector = sectors.get(code, {})
        # 行业字段只能写入实际获取到的申万层级，不能用普通 industry 伪造层级。
        sector_1 = sector.get("sector_1")
        sector_2 = sector.get("sector_2")
        sector_3 = sector.get("sector_3")
        total_share, float_share = shares.get(code, (None, None))
        rows.append((code, _text(item.get("name")), _date(item.get("list_date")), total_share, float_share, sector_1, sector_2, sector_3))

    if write and rows:
        execute_many(
            "INSERT INTO trade_stock_status "
            "(stock_code, stock_name, list_date, total_shares, float_shares, sector_1, sector_2, sector_3) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE stock_name=VALUES(stock_name), list_date=VALUES(list_date), "
            "total_shares=COALESCE(VALUES(total_shares), total_shares), "
            "float_shares=COALESCE(VALUES(float_shares), float_shares), "
            "sector_1=COALESCE(VALUES(sector_1), sector_1), "
            "sector_2=COALESCE(VALUES(sector_2), sector_2), "
            "sector_3=COALESCE(VALUES(sector_3), sector_3)",
            rows,
        )
    return {"trade_date": trade_date, "rows": len(rows), "shares": len(shares), "sectors": len(sectors), "write": write}


def _date(value):
    value = _text(value)
    if not value:
        return None
    value = value[:10].replace("-", "")
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 else value


class TushareIndustrySyncTest(unittest.TestCase):
    @unittest.skipUnless(ts is not None and _load_token(), "需要安装 tushare 并设置 TUSHARE_TOKEN")
    def test_sync_trade_stock_status(self):
        token = _load_token()
        pro = _new_tushare_client(token)
        result = sync_trade_stock_status(pro, write=os.getenv("STOCK_STATUS_SYNC_WRITE", "1") != "0")
        print(f"trade_stock_status 同步结果: {result}")
        self.assertGreater(result["rows"], 0)


if __name__ == "__main__":
    unittest.main()
