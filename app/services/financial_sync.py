# -*- coding: utf-8 -*-
"""财务数据同步：akshare 跨平台方案（macOS / Windows / Linux 均可用）

替代原 QMT(xtquant, 仅 Windows) 方案，双接口配合：
- 主路径：stock_yjbb_em 东财业绩报表，按报告期全市场批量拉取（快，秒级）
  → 覆盖 营收/净利润/EPS/ROE/毛利率
- 补全：stock_financial_abstract 东财财务摘要，逐股拉取（慢）
  → 覆盖 总资产/净资产/ROA/净利率/资产负债率/流动比率/经营现金流总额
  默认关闭（enrich_detail=False），需对重点股票精确指标时开启

同步策略：增量 upsert，唯一键 (stock_code, report_date)，重复自动更新。
"""
import logging
from datetime import date
from functools import lru_cache
from typing import Optional

import akshare as ak

from app.database import execute_many

logger = logging.getLogger(__name__)

# 写入 SQL（唯一键 stock_code + report_date，重复则更新）
INSERT_SQL = """
INSERT INTO trade_stock_financial
(stock_code, report_date, revenue, net_profit, eps, roe, roa, gross_margin,
 net_margin, operating_cashflow, total_assets, total_equity, debt_ratio,
 current_ratio, data_source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
revenue=COALESCE(VALUES(revenue), revenue),
net_profit=COALESCE(VALUES(net_profit), net_profit),
eps=COALESCE(VALUES(eps), eps),
roe=COALESCE(VALUES(roe), roe), roa=COALESCE(VALUES(roa), roa),
gross_margin=COALESCE(VALUES(gross_margin), gross_margin),
net_margin=COALESCE(VALUES(net_margin), net_margin),
operating_cashflow=COALESCE(VALUES(operating_cashflow), operating_cashflow),
total_assets=COALESCE(VALUES(total_assets), total_assets),
total_equity=COALESCE(VALUES(total_equity), total_equity),
debt_ratio=COALESCE(VALUES(debt_ratio), debt_ratio),
current_ratio=COALESCE(VALUES(current_ratio), current_ratio),
data_source=VALUES(data_source)
"""


def _num(v):
    """转 float；空值/占位符返回 None"""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip().replace(",", "")
        if v in ("", "--", "-", "None", "nan"):
            return None
    try:
        f = float(v)
        return None if f != f else f  # 过滤 NaN
    except (TypeError, ValueError):
        return None


def _first_num(row, *names):
    """按候选列名读取第一个有效数值，兼容 AkShare 字段名变化。"""
    for name in names:
        if name in row:
            value = _num(row.get(name))
            if value is not None:
                return value
    return None


def _quarter_end_dates(n: int = 2, end: Optional[date] = None) -> list:
    """返回截至 end 最近 n 个已结束/当季季度末（从最近往前）"""
    end = end or date.today()
    res = []
    y, m = end.year, end.month
    for _ in range(n):
        qm = ((m - 1) // 3) * 3 + 3  # 当前所处季度的季末月 3/6/9/12
        if m < qm:  # 还没到季末月，回退到上一季度末
            m = 12 if qm == 3 else qm - 3
            if qm == 3:
                y -= 1
        d = 30 if ((m - 1) // 3) in (1, 2) else 31  # 6/9 月 30 天，3/12 月 31 天
        res.append(date(y, m, d))
        # 移到上一季度
        if m == 3:
            y, m = y - 1, 12
        else:
            m -= 3
    return res


def _abstract_map(df) -> dict:
    """把财务摘要宽表转成 {指标名: 行Series}，保留首次出现（常用指标区）"""
    m = {}
    for _, r in df.iterrows():
        name = str(r.get("指标", "")).strip()
        if name and name not in m:
            m[name] = r
    return m


@lru_cache(maxsize=256)
def _balance_sheet_map(code: str) -> dict:
    """读取资产负债表，兼容沪市 B 股代码；返回 {报告期: 行}。"""
    symbol = f"sh{code}" if code.startswith("9") else code
    try:
        df = ak.stock_financial_report_sina(stock=symbol, symbol="资产负债表")
    except Exception as e:
        logger.warning("[财务] %s 资产负债表拉取失败: %s", code, e)
        return {}
    if df is None or df.empty or "报告日" not in df.columns:
        return {}
    return {
        str(row.get("报告日", "")).strip(): row
        for _, row in df.iterrows()
        if str(row.get("报告日", "")).strip()
    }


def _enrich_one(code: str, rd_str: str) -> Optional[dict]:
    """单股单报告期补全明细指标；失败返回 None"""
    try:
        df = ak.stock_financial_abstract(symbol=code)
    except Exception as e:
        logger.warning("[财务] %s 财务摘要拉取失败: %s", code, e)
        df = None
    m = _abstract_map(df) if df is not None and not df.empty else {}
    balance = _balance_sheet_map(code)
    balance_row = balance.get(rd_str, {})

    def v(*names):
        for name in names:
            row = m.get(name)
            if row is None:
                continue
            val = _num(row.get(rd_str))
            if val is not None:
                return val
        return None

    return {
        "revenue": v("营业总收入"),
        "net_profit": v("归母净利润", "净利润"),
        "eps": v("基本每股收益"),
        "roe": v("净资产收益率(ROE)"),
        "roa": v("总资产报酬率(ROA)"),
        "gross_margin": v("毛利率"),
        "net_margin": v("销售净利率"),
        "debt_ratio": v("资产负债率"),
        "current_ratio": v("流动比率"),
        "operating_cashflow": v("经营现金流量净额"),
        "total_assets": _first_num(balance_row, "资产总计", "负债和所有者权益(或股东权益)总计")
        if balance_row is not None and len(balance_row) else v("资产总计", "总资产"),
        "total_equity": _first_num(
            balance_row,
            "所有者权益(或股东权益)合计",
            "归属于母公司股东权益合计",
        ) if balance_row is not None and len(balance_row) else v("股东权益合计(净资产)"),
    }


def sync_financial(
    stock_codes: Optional[list] = None,
    quarters: int = 2,
    enrich_detail: bool = False,
    test_mode: bool = False,
) -> dict:
    """akshare 跨平台财务同步

    Args:
        stock_codes: 指定股票代码（6 位，如 ["600519"]）；None 表示全市场
        quarters: 同步最近几个报告期（默认 2 个季度）
        enrich_detail: 是否逐股补全明细指标（慢，适合少量重点股）
        test_mode: 测试模式，仅同步少量股票
    """
    if test_mode:
        stock_codes = ["600519", "000001", "300750"]
        quarters = min(quarters, 1)
        logger.info("[财务] 测试模式，仅同步 %s", stock_codes)

    report_dates = _quarter_end_dates(quarters)
    total_written = 0
    total_rows = 0

    for rd in report_dates:
        rd_str = rd.strftime("%Y%m%d")
        rd_fmt = rd.isoformat()
        logger.info("[财务] 拉取报告期 %s 业绩报表...", rd)
        try:
            df = ak.stock_yjbb_em(date=rd_str)
        except Exception as e:
            logger.warning("[财务] 报告期 %s 拉取失败: %s", rd, e)
            continue

        rows = []
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            if not code or (stock_codes and code not in stock_codes):
                continue
            rows.append((
                code, rd_fmt,
                _first_num(r, "营业总收入-营业总收入", "营业总收入"),
                _first_num(r, "净利润-净利润", "归母净利润", "净利润"),
                _first_num(r, "每股收益", "基本每股收益"),
                _first_num(r, "净资产收益率", "净资产收益率(ROE)"),
                None,   # ROA 待 enrich 补全
                _first_num(r, "销售毛利率", "毛利率"),
                None,   # 净利率待 enrich 补全
                None, None, None, None, None,  # 明细字段待 enrich 补全
                "akshare",
            ))

        if rows:
            written = execute_many(INSERT_SQL, rows)
            total_written += written
            total_rows += len(rows)
            logger.info("[财务] 报告期 %s 写入 %s 行", rd, written)

        # 补全明细指标（逐股，慢）：独立于业绩报表，对目标股票逐个拉取
        if enrich_detail:
            detail_written = 0
            target = stock_codes or [str(r.get("股票代码", "")).strip() for _, r in df.iterrows() if str(r.get("股票代码", "")).strip()]
            for code in dict.fromkeys(target):
                d = _enrich_one(code, rd_str)
                if not d:
                    continue
                detail_written += execute_many(INSERT_SQL, [(
                    code, rd_fmt,
                    d["revenue"], d["net_profit"], d["eps"], d["roe"],
                    d["roa"], d["gross_margin"], d["net_margin"],
                    d["operating_cashflow"], d["total_assets"],
                    d["total_equity"], d["debt_ratio"], d["current_ratio"],
                    "akshare",
                )])
            total_written += detail_written
            logger.info("[财务] 报告期 %s 明细补全 %s 行", rd, detail_written)

    return {
        "source": "akshare",
        "written": total_written,
        "skipped": 0,
        "total": total_rows,
        "reports": len(report_dates),
        "enrich_detail": enrich_detail,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(sync_financial(test_mode=True))
