# -*- coding: utf-8 -*-
"""申万行业元数据同步（akshare + baostock）
迁移自: 11周 industry_meta.py
表: trade_stock_status (sector_1/sector_2/sector_3 + total_shares/float_shares)
"""
import logging
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import akshare as ak

from app.database import execute_many, execute_query, execute_update

logger = logging.getLogger(__name__)


def _fetch_stock_shares_baostock(codes: list[str]) -> dict[str, dict[str, int]]:
    """通过 baostock 获取总股本/流通股本（单位：股）"""
    import baostock as bs

    result: dict[str, dict[str, int]] = {}
    lg = bs.login()
    if lg.error_code != "0":
        logger.warning("baostock 登录失败: %s", lg.error_msg)
        return result

    try:
        for code in codes:
            bs_code = f"sh.{code}" if code.startswith(("6", "9")) else f"sz.{code}"
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code, "date,totalShare,liqaShare",
                    start_date="2020-01-01", end_date="2026-12-31",
                    frequency="d", adjustflag="3",
                )
                data_list = []
                while rs.error_code == "0" and rs.next():
                    data_list.append(rs.get_row_data())
                if data_list:
                    last = data_list[-1]
                    result[code] = {
                        "total_shares": int(float(last[1]) * 10000) if last[1] else None,
                        "float_shares": int(float(last[2]) * 10000) if last[2] else None,
                    }
            except Exception:
                continue
    finally:
        bs.logout()
    logger.info("[行业] baostock 股本获取完成: %d/%d", len(result), len(codes))
    return result


def _normalize_code(value: object) -> str:
    """统一为六位股票代码，避免接口返回数字时丢失前导零。"""
    code = str(value).strip().split(".")[0]
    return code.zfill(6) if code.isdigit() else code


def _init_stock_base() -> tuple[int, str | None]:
    """当状态表为空时尝试初始化股票基础列表，失败不阻断行业同步。"""
    rows = execute_query("SELECT COUNT(*) AS total FROM trade_stock_status")
    if rows and rows[0]["total"]:
        return 0, None

    try:
        try:
            df = ak.stock_zh_a_spot_em()
        except Exception:
            df = ak.stock_info_a_code_name()
        if df is None or df.empty:
            raise RuntimeError("AkShare 未返回股票基础列表")

        values = []
        for _, row in df.iterrows():
            code = _normalize_code(row.get("代码", row.get("股票代码", row.get("code", ""))))
            name = str(row.get("名称", row.get("股票简称", row.get("name", "")))).strip()
            if code and len(code) == 6 and name and name != "nan":
                values.append((code, name))

        if not values:
            raise RuntimeError("股票基础列表中没有有效股票代码")

        inserted = execute_many(
            "INSERT INTO trade_stock_status (stock_code, stock_name) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE stock_name=VALUES(stock_name)",
            values,
        )
        logger.info("[行业] 股票基础数据初始化完成: %d 条", inserted)
        return inserted, None
    except Exception as exc:
        message = f"股票基础列表初始化失败，将由行业成分数据创建记录: {exc}"
        logger.warning("[行业] %s", message)
        return 0, message


def sync_industry(fetch_shares: bool = True) -> dict:
    """同步申万行业分类到 trade_stock_status。"""
    init_count, init_warning = _init_stock_base()

    # 1. 申万一级/二级/三级行业成分股映射
    stock_industry: dict[str, dict[str, str]] = {}
    industry_sources = (
        ("sector_1", "sw_index_first_info", "申万一级"),
        ("sector_2", "sw_index_second_info", "申万二级"),
        ("sector_3", "sw_index_third_info", "申万三级"),
    )
    for target, source_name, label in industry_sources:
        try:
            directory = getattr(ak, source_name)()
            if directory is None or directory.empty:
                raise RuntimeError(f"{label}行业目录为空")
            for _, row in directory.iterrows():
                code = str(row["行业代码"]).replace(".SI", "").strip()
                name = str(row["行业名称"]).strip()
                if not code or not name or name == "nan":
                    continue
                df = ak.index_stock_cons(symbol=code)
                for _, member in df.iterrows():
                    scode = _normalize_code(member["品种代码"])
                    if scode:
                        stock_industry.setdefault(scode, {})[target] = name
        except Exception as exc:
            logger.warning("[行业] %s行业获取失败: %s", label, exc)

    # 2. 落库 trade_stock_status，只覆盖实际获取到的层级，避免空响应抹掉旧数据。
    upsert_sql = """
        INSERT INTO trade_stock_status (stock_code, sector_1, sector_2, sector_3)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            sector_1=COALESCE(VALUES(sector_1), sector_1),
            sector_2=COALESCE(VALUES(sector_2), sector_2),
            sector_3=COALESCE(VALUES(sector_3), sector_3)
    """
    updated = 0
    for scode, m in stock_industry.items():
        updated += execute_update(upsert_sql, (scode, m.get("sector_1"), m.get("sector_2"), m.get("sector_3")))

    # 3. 股本更新（baostock）
    shares_updated = 0
    if fetch_shares and stock_industry:
        shares = _fetch_stock_shares_baostock(list(stock_industry.keys()))
        for scode, s in shares.items():
            if s["total_shares"]:
                shares_updated += execute_update(
                    "UPDATE trade_stock_status SET total_shares=%s, float_shares=%s WHERE stock_code=%s",
                    (s["total_shares"], s["float_shares"], scode),
                )

    result = {
        "industry_updated": updated,
        "shares_updated": shares_updated,
        "stocks": len(stock_industry),
        "initialized": init_count,
        "init_warning": init_warning,
    }
    if not stock_industry:
        raise RuntimeError("申万行业接口未返回任何股票成分数据")
    if updated == 0:
        raise RuntimeError("行业数据获取成功但数据库没有写入记录")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(sync_industry(fetch_shares=False))


def list_sectors_from_db(level: int = 2) -> list[str]:
    """查询 DB 中已有板块列表（去重）"""
    col = "sector_1" if level == 1 else "sector_2"
    rows = execute_query(
        f"SELECT DISTINCT {col} AS name FROM trade_stock_status WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}"
    )
    return [r["name"] for r in rows]


def get_sector_member_codes(sector_name: str, level: int = 2) -> list[str]:
    """获取某板块的成分股代码"""
    col = "sector_1" if level == 1 else "sector_2"
    rows = execute_query(
        f"SELECT stock_code FROM trade_stock_status WHERE {col} = %s", (sector_name,)
    )
    return [r["stock_code"] for r in rows]
